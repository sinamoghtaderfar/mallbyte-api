import random
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

class UserManager(BaseUserManager):
    def create_user(self, phone, email, full_name, password=None, **extra_fields):
        if not phone:
            raise ValueError("Phone number is required")
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)
        user = self.model(phone=phone, email=email, full_name=full_name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, email, full_name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(phone, email, full_name, password, **extra_fields)


class User(AbstractUser):
    """
    Custom User model - login using phone number
    """

    # Remove the default username field
    username = None

    # Unique phone for login
    phone = models.CharField(max_length=15, unique=True, verbose_name="Phone Number")

    # Unique email
    email = models.EmailField(unique=True, verbose_name="Email")

    # Full name user
    full_name = models.CharField(max_length=255, verbose_name="Full Name")

    # Flag to indicate if the user is a seller
    is_seller = models.BooleanField(default=False, verbose_name="Is Seller?")

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
    roles = models.ManyToManyField(
        'rbac.Role',
        through='rbac.UserRole',
        through_fields=('user', 'role'),
        related_name='users',
        blank=True,
        verbose_name="Roles"
    )
    # Field used for login
    USERNAME_FIELD = "phone"

    # Required fields when creating superuser
    REQUIRED_FIELDS = ["email", "full_name"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    # String representation of the user
    def __str__(self):
        return f"{self.full_name} - {self.phone}"


class Profile(models.Model):
    """User profile model"""

    GENDER_CHOICES = [
        ("M", "Male"),
        ("F", "Female"),
        ("O", "Other"),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="profile", verbose_name="User"
    )

    avatar = models.ImageField(
        upload_to="avatars/", null=True, blank=True, verbose_name="Avatar"
    )
    birth_date = models.DateField(null=True, blank=True, verbose_name="Birth Date")
    gender = models.CharField(
        max_length=1,
        choices=GENDER_CHOICES,
        null=True,
        blank=True,
        verbose_name="Gender",
    )
    national_code = models.CharField(
        max_length=10, null=True, blank=True, verbose_name="National Code"
    )
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

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="addresses", verbose_name="User"
    )

    title = models.CharField(
        max_length=255, verbose_name="Address Title", help_text="e.g., Home, Work, etc."
    )

    province = models.CharField(max_length=255, verbose_name="Province")

    city = models.CharField(max_length=255, verbose_name="City")
    street = models.CharField(max_length=255, verbose_name="Street")
    alley = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Alley"
    )
    building_number = models.CharField(
        max_length=20, verbose_name="Building/Plate Number"
    )
    floor = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Floor"
    )
    unit = models.CharField(max_length=20, blank=True, null=True, verbose_name="Unit")
    postal_code = models.CharField(max_length=10, verbose_name="Postal Code")
    receiver_name = models.CharField(max_length=255, verbose_name="Receiver Name")
    receiver_phone = models.CharField(max_length=11, verbose_name="Receiver Phone")
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
            Address.objects.filter(user=self.user, is_default=True).update(
                is_default=False
            )
        super().save(*args, **kwargs)


import random
from django.utils import timezone
from datetime import timedelta

class OTP(models.Model):
    """One-time password for phone verification"""
    phone = models.CharField(max_length=15, verbose_name="Phone Number")
    code = models.CharField(max_length=6, verbose_name="Verification Code")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(verbose_name="Expires At")
    is_used = models.BooleanField(default=False, verbose_name="Is Used")
    
    class Meta:
        verbose_name = "OTP"
        verbose_name_plural = "OTPs"
        indexes = [
            models.Index(fields=['phone', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.phone} - {self.code} - {'Used' if self.is_used else 'Active'}"
    
    @property
    def is_expired(self):
        """Check if OTP is expired"""
        return timezone.now() > self.expires_at
    
    @classmethod
    def generate_otp(cls, phone):
        """Generate a new OTP for phone number"""
        # Expire old OTPs for this phone
        cls.objects.filter(phone=phone, is_used=False).update(is_used=True)
        
        # Generate 6-digit code
        code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        
        # Set expiry to 2 minutes from now
        expires_at = timezone.now() + timedelta(minutes=2)
        
        # Create and return new OTP
        otp = cls.objects.create(
            phone=phone,
            code=code,
            expires_at=expires_at
        )
        return otp
    
    @classmethod
    def verify_otp(cls, phone, code):
        """Verify OTP code for phone number"""
        try:
            otp = cls.objects.filter(
                phone=phone,
                code=code,
                is_used=False
            ).latest('created_at')
            
            if otp.is_expired:
                return False, "OTP has expired"
            
            # Mark as used
            otp.is_used = True
            otp.save()
            
            return True, "OTP verified successfully"
            
        except cls.DoesNotExist:
            return False, "Invalid OTP code"
        
class Seller(models.Model):
    """Seller information for multi-vendor marketplace"""

    class StatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        SUSPENDED = 'suspended', 'Temporarily Suspended'

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="seller",
        verbose_name="User"
    )

    store_name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Store Name"
    )

    store_slug = models.SlugField(
        max_length=120,
        unique=True,
        verbose_name="Store Slug"
    )

    logo = models.ImageField(
        upload_to='sellers/logos/',
        null=True,
        blank=True,
        verbose_name="Logo"
    )

    banner = models.ImageField(
        upload_to='sellers/banners/',
        null=True,
        blank=True,
        verbose_name="Banner"
    )

    description = models.TextField(
        max_length=500,
        blank=True,
        verbose_name="Store Description"
    )

    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
        verbose_name="Status"
    )
    
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_sellers',
        verbose_name="Verified By"
    )
    
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Verified At"
    )
    
    rejection_reason = models.TextField(
        blank=True,
        verbose_name="Rejection Reason"
    )
    
     # Contact & Business info
    business_phone = models.CharField(
        max_length=15,
        verbose_name="Business Phone"
    )
    business_email = models.EmailField(
        verbose_name="Business Email"
    )
    website = models.URLField(
        blank=True,
        verbose_name="Website"
    )
    
    # Bank info (store as JSON for flexibility)
    bank_info = models.JSONField(
        default=dict,
        verbose_name="Bank Information",
        help_text="Store bank account details as JSON"
    )
    
    # Documents (store paths as JSON)
    documents = models.JSONField(
        default=list,
        verbose_name="Documents",
        help_text="List of uploaded document paths"
    )
    
    # Financial
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10.00,
        verbose_name="Commission Rate (%)",
        help_text="Percentage taken by platform"
    )
    
    total_sales = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        verbose_name="Total Sales"
    )
    total_orders = models.PositiveIntegerField(
        default=0,
        verbose_name="Total Orders"
    )
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
        verbose_name="Current Balance"
    )
    
    # Timestamps
    applied_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Applied At"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At"
    )
    
    class Meta:
        verbose_name = "Seller"
        verbose_name_plural = "Sellers"
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['store_slug']),
            models.Index(fields=['-total_sales']),
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
    
    def approve(self, admin_user):
        """Approve seller application"""
        self.status = self.StatusChoices.APPROVED
        self.verified_by = admin_user
        self.verified_at = timezone.now()
        self.save()
        
        from apps.rbac.utils import assign_role
        from apps.rbac.models import Role
        
        try:
            vendor_role = Role.objects.get(name='vendor')
            assign_role(self.user, vendor_role, admin_user)
            print(f" Role 'vendor' assigned to user {self.user.phone}")
        except Role.DoesNotExist:
            print(" Role 'vendor' not found!")
    
    def reject(self, admin_user, reason):
        """Reject seller application"""
        self.status = self.StatusChoices.REJECTED
        self.verified_by = admin_user
        self.rejection_reason = reason
        self.save()
    
        try:
            vendor_role = Role.objects.get(name='vendor')
            remove_role(self.user, vendor_role)
            print(f" Role 'vendor' removed from user {self.user.phone}")
        except Role.DoesNotExist:
            pass
        
    @property
    def is_verified(self):
        return self.status == self.StatusChoices.APPROVED