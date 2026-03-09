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
    phone = models.CharField(max_length=11, unique=True, verbose_name="Phone Number")

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
