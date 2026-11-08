import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, models, router, transaction
from django.db.models import F
from django.db.models.functions import Lower
from django.utils import timezone


class UserManager(BaseUserManager):
    @classmethod
    def normalize_email(cls, email):
        return super().normalize_email(email).strip().lower()

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    def all_with_deleted(self):
        return super().get_queryset()

    def get(self, *args, **kwargs):
        return self.get_queryset().get(*args, **kwargs)

    def create_user(self, email, full_name="", password=None, phone=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)
        user = self.model(
            email=email,
            full_name=full_name,
            phone=phone,
            **extra_fields,
    )
        user.set_password(password)
        user.save(using=self._db)
        return user


    def create_superuser(self, email, full_name="", password=None, phone=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")

        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(
        email=email,
        full_name=full_name,
        password=password,
        phone=phone,
        **extra_fields,
    )


class User(AbstractUser):
    """
    Custom user model using email as the primary login identifier
    """

    # Remove the default username field
    username = None
    _SECURITY_FIELDS = frozenset({"password", "email", "email_verified", "is_active", "is_deleted", "is_staff", "is_superuser"})

    phone = models.CharField(
    max_length=15,
    unique=True,
    null=True,
    blank=True,
    verbose_name="Phone Number",
    )

    # Unique email
    email = models.EmailField(unique=True, verbose_name="Email")

    # Full name user
    full_name = models.CharField(max_length=255, verbose_name="Full Name")

    # Flag to indicate if the user is a seller
    is_seller = models.BooleanField(default=False, verbose_name="Is Seller?")

    # Soft delete field
    is_deleted = models.BooleanField(default=False, verbose_name="Is Deleted")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Deleted At")

    # email verification fields
    email_verified = models.BooleanField(default=False, verbose_name="Email Verified")
    email_verified_at = models.DateTimeField(null=True, blank=True, verbose_name="Email Verified At")
    # JWTs issued before an ownership/security transition must not become valid later.
    auth_version = models.PositiveIntegerField(default=1, editable=False)

    # Custom admin
    objects = UserManager()

    groups = models.ManyToManyField(
        "auth.Group",
        verbose_name="groups",
        blank=True,
        help_text="The groups this user belongs to.",
        related_name="custom_user_set",  # changed from default 'user_set'
        related_query_name="custom_user",
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission",
        verbose_name="user permissions",
        blank=True,
        help_text="Specific permissions for this user.",
        related_name="custom_user_set",  # changed from default 'user_set'
        related_query_name="custom_user_permissions",
    )
    roles = models.ManyToManyField("rbac.Role", through="rbac.UserRole", through_fields=("user", "role"), related_name="users", blank=True, verbose_name="Roles")
    
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        constraints = [models.UniqueConstraint(Lower("email"), name="accounts_user_email_case_insensitive_unique")]

    # String representation of the user
    def __str__(self):
        return f"{self.full_name} - {self.email}"

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_security_state = {name: value for name, value in zip(field_names, values, strict=True) if name in cls._SECURITY_FIELDS}
        return instance

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        self._loaded_security_state = {field: getattr(self, field) for field in self._SECURITY_FIELDS if field not in self.get_deferred_fields()}

    def save(self, *args, **kwargs):
        """Invalidate sessions for security changes, including Django admin saves."""
        if "email" not in self.get_deferred_fields():
            self.email = type(self).objects.normalize_email(self.email)
        security_fields = self._SECURITY_FIELDS
        update_fields = kwargs.get("update_fields")
        if self._state.adding:
            result = super().save(*args, **kwargs)
            self._loaded_security_state = {field: getattr(self, field) for field in security_fields if field not in self.get_deferred_fields()}
            return result
        if update_fields is not None and not security_fields.intersection(update_fields):
            return super().save(*args, **kwargs)
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=database):
            previous = type(self)._base_manager.using(database).select_for_update().filter(pk=self.pk).values(*security_fields, "auth_version").first()
            if previous is not None:
                relevant = security_fields if update_fields is None else security_fields.intersection(update_fields)
                loaded = getattr(self, "_loaded_security_state", {})
                changed = False
                for field in relevant:
                    # A full save of stale profile data must not undo a newer
                    # password/identity change made through another instance.
                    explicitly_changed = field in loaded and getattr(self, field) != loaded[field]
                    if field not in loaded and update_fields is not None and field not in self.get_deferred_fields():
                        explicitly_changed = True
                    if explicitly_changed:
                        changed = changed or previous[field] != getattr(self, field)
                    else:
                        setattr(self, field, previous[field])
                self.auth_version = previous["auth_version"] + int(changed)
                if changed and update_fields is not None:
                    kwargs["update_fields"] = set(update_fields) | {"auth_version"}
            result = super().save(*args, **kwargs)
            self._loaded_security_state = {field: getattr(self, field) for field in security_fields if field not in self.get_deferred_fields()}
            return result

    def invalidate_sessions(self):
        """Atomically revoke all access and refresh sessions for this account."""
        type(self)._base_manager.filter(pk=self.pk).update(auth_version=F("auth_version") + 1)
        self.refresh_from_db(fields=["auth_version"])


class Profile(models.Model):
    """User profile model"""

    GENDER_CHOICES = [
        ("M", "Male"),
        ("F", "Female"),
        ("O", "Other"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile", verbose_name="User")

    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True, verbose_name="Avatar")
    birth_date = models.DateField(null=True, blank=True, verbose_name="Birth Date")
    gender = models.CharField(
        max_length=1,
        choices=GENDER_CHOICES,
        null=True,
        blank=True,
        verbose_name="Gender",
    )
    national_code = models.CharField(max_length=10, null=True, blank=True, verbose_name="National Code")
    loyalty_points = models.IntegerField(default=0, verbose_name="Loyalty Points")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"

    def __str__(self):
        return f"{self.user.full_name}'s Profile"


class Address(models.Model):
    """User addresses model"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses", verbose_name="User")

    title = models.CharField(max_length=255, verbose_name="Address Title", help_text="e.g., Home, Work, etc.")

    province = models.CharField(max_length=255, verbose_name="Province")

    city = models.CharField(max_length=255, verbose_name="City")
    street = models.CharField(max_length=255, verbose_name="Street")
    alley = models.CharField(max_length=255, blank=True, null=True, verbose_name="Alley")
    building_number = models.CharField(max_length=20, verbose_name="Building/Plate Number")
    floor = models.CharField(max_length=255, blank=True, null=True, verbose_name="Floor")
    unit = models.CharField(max_length=20, blank=True, null=True, verbose_name="Unit")
    postal_code = models.CharField(max_length=20, verbose_name="Postal Code")
    receiver_name = models.CharField(max_length=255, verbose_name="Receiver Name")
    receiver_phone = models.CharField(max_length=20, verbose_name="Receiver Phone")
    is_default = models.BooleanField(default=False, verbose_name="Default Address")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Address"
        verbose_name_plural = "Addresses"
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return f"{self.title}: {self.city}, {self.street}"

    def save(self, *args, **kwargs):
        # If this address is set as default, unset other default addresses for this user
        if self.is_default:
            Address.objects.filter(user=self.user, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)


class OTP(models.Model):
    """One-time password for email verification"""

    phone = models.CharField(
    max_length=15,
    null=True,
    blank=True,
    verbose_name="Phone Number",
    )
    code = models.CharField(max_length=6, verbose_name="Verification Code")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(verbose_name="Expires At")
    is_used = models.BooleanField(default=False, verbose_name="Is Used")
    email = models.EmailField(
    db_index=True,
    verbose_name="Email Address",
    )

    class Meta:
        verbose_name = "OTP"
        verbose_name_plural = "OTPs"
        constraints = [models.UniqueConstraint(fields=["email"], condition=models.Q(is_used=False), name="accounts_otp_one_unused_per_email")]
        indexes = [
            models.Index(fields=["email", "created_at"]),
        ]

    def __str__(self):
        identifier = self.email or self.phone or "unknown"
        return f"{identifier} - {'Used' if self.is_used else 'Active'}"

    @property
    def is_expired(self):
        """Check if OTP is expired"""
        return timezone.now() > self.expires_at

    @classmethod
    def generate_otp(cls, email):
        """Generate a new OTP for an email address."""
        normalized_email = email.strip().lower()

        # The unique partial index serializes even a first issuance, where
        # there is no existing row to lock. Retry a competing insertion.
        for attempt in range(3):
            try:
                with transaction.atomic():
                    cls.objects.filter(email=normalized_email, is_used=False).update(is_used=True)
                    return cls.objects.create(
                        email=normalized_email,
                        code="".join(str(secrets.randbelow(10)) for _ in range(6)),
                        expires_at=timezone.now() + timedelta(seconds=getattr(settings, "OTP_CODE_EXPIRY_SECONDS", 120)),
                    )
            except IntegrityError:
                if attempt == 2:
                    raise

    @classmethod
    def verify_otp(cls, email, code):
        """Verify OTP code for an email address."""
        success, message, _otp = cls.verify_otp_and_get_instance(
            email=email,
            code=code,
    )

        return success, message

    @classmethod
    def verify_otp_and_get_instance(cls, email, code):
        """Verify OTP code and return the OTP instance."""
        normalized_email = email.strip().lower()

        try:
            otp = cls.objects.filter(
                email=normalized_email,
                code=code,
                is_used=False,
            ).latest("created_at")

            if otp.is_expired:
                return False, "OTP has expired", None

            consumed = cls.objects.filter(pk=otp.pk, is_used=False, expires_at__gt=timezone.now()).update(is_used=True)
            if not consumed:
                return False, "Invalid OTP code", None
            otp.is_used = True

            return True, "OTP verified successfully", otp

        except cls.DoesNotExist:
            return False, "Invalid OTP code", None

class Seller(models.Model):
    """Seller information for multi-vendor marketplace"""

    class StatusChoices(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SUSPENDED = "suspended", "Temporarily Suspended"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="seller", verbose_name="User")

    store_name = models.CharField(max_length=100, unique=True, verbose_name="Store Name")

    store_slug = models.SlugField(max_length=120, unique=True, verbose_name="Store Slug")

    logo = models.ImageField(upload_to="sellers/logos/", null=True, blank=True, verbose_name="Logo")

    banner = models.ImageField(upload_to="sellers/banners/", null=True, blank=True, verbose_name="Banner")

    description = models.TextField(max_length=500, blank=True, verbose_name="Store Description")

    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.PENDING, verbose_name="Status")

    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_sellers", verbose_name="Verified By")

    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="Verified At")

    rejection_reason = models.TextField(blank=True, verbose_name="Rejection Reason")

    # Contact & Business info
    business_phone = models.CharField(max_length=15, verbose_name="Business Phone")
    business_email = models.EmailField(verbose_name="Business Email")
    website = models.URLField(blank=True, verbose_name="Website")

    # Bank info (store as JSON for flexibility)
    bank_info = models.JSONField(default=dict, verbose_name="Bank Information", help_text="Store bank account details as JSON")

    # Documents (store paths as JSON)
    documents = models.JSONField(default=list, verbose_name="Documents", help_text="List of uploaded document paths")

    # Financial
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=10.00, verbose_name="Commission Rate (%)", help_text="Percentage taken by platform")

    total_sales = models.DecimalField(max_digits=12, decimal_places=0, default=0, verbose_name="Total Sales")
    total_orders = models.PositiveIntegerField(default=0, verbose_name="Total Orders")
    balance = models.DecimalField(max_digits=12, decimal_places=0, default=0, verbose_name="Current Balance")

    # Timestamps
    applied_at = models.DateTimeField(auto_now_add=True, verbose_name="Applied At")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")

    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Seller"
        verbose_name_plural = "Sellers"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["store_slug"]),
            models.Index(fields=["-total_sales"]),
        ]

    def __str__(self):
        return f"{self.store_name} - {self.get_status_display()}"

    def save(self, *args, **kwargs):
        # Auto-generate slug from store name if not provided
        if not self.store_slug:
            from django.utils.text import slugify

            base_slug = slugify(self.store_name)
            slug = base_slug
            counter = 1
            while Seller.objects.filter(store_slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.store_slug = slug
        super().save(*args, **kwargs)

    def _decide_application(self, admin_user, *, approve, reason=""):
        from apps.rbac.models import Role
        from apps.rbac.utils import assign_role, has_permission, remove_role

        permission = "approve_seller" if approve else "reject_seller"
        if not has_permission(admin_user, permission):
            raise PermissionDenied("Seller decision permission required.")
        if not approve and (not isinstance(reason, str) or len(reason.strip()) < 3 or len(reason) > 2000):
            raise ValidationError("A rejection reason between 3 and 2000 characters is required.")

        with transaction.atomic():
            # Checkout uses the same User -> Seller order. NO KEY UPDATE permits
            # concurrent foreign-key references without weakening row exclusion.
            user = User.objects.all_with_deleted().select_for_update(no_key=True).get(pk=self.user_id)
            seller = type(self).objects.select_for_update(no_key=True).get(pk=self.pk)
            if seller.status != self.StatusChoices.PENDING:
                raise ValidationError("Only pending seller applications can be decided.")
            if approve and (not user.is_active or user.is_deleted):
                raise ValidationError("An unavailable account cannot become a seller.")
            try:
                vendor_role = Role.objects.get(name="vendor")
            except Role.DoesNotExist as exc:
                raise ValidationError("Vendor role is not configured; no seller state was changed.") from exc

            seller.status = self.StatusChoices.APPROVED if approve else self.StatusChoices.REJECTED
            seller.verified_by = admin_user
            seller.verified_at = timezone.now()
            seller.rejection_reason = "" if approve else reason.strip()
            seller.save(update_fields=["status", "verified_by", "verified_at", "rejection_reason", "updated_at"])
            user.is_seller = approve
            user.save(update_fields=["is_seller"])
            if approve:
                assign_role(user, vendor_role, admin_user)
            else:
                remove_role(user, vendor_role)
            self.refresh_from_db()

    def approve(self, admin_user):
        """Atomically approve a pending application and grant its vendor role."""
        return self._decide_application(admin_user, approve=True)

    def reject(self, admin_user, reason):
        """Atomically reject a pending application and revoke its vendor role."""
        return self._decide_application(admin_user, approve=False, reason=reason)

    @property
    def is_verified(self):
        return self.status == self.StatusChoices.APPROVED


# Django discovers the MFA models through this module.
from .mfa_models import AdminMFAChallenge, AdminMFADevice  # noqa: E402,F401
