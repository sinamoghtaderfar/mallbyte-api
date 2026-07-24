from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        ORDER = "order", "Order"
        PAYMENT = "payment", "Payment"
        SHIPPING = "shipping", "Shipping"
        RETURN = "return", "Return"
        DISCOUNT = "discount", "Discount"
        SYSTEM = "system", "System"
        PRODUCT = "product", "Product"
        INVENTORY = "inventory", "Inventory"

    class Channel(models.TextChoices):
        IN_APP = "in_app", "In App"
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        PUSH = "push", "Push"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    title = models.CharField(max_length=255)
    message = models.TextField()

    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        default=NotificationType.SYSTEM,
        db_index=True,
    )

    channel = models.CharField(
        max_length=30,
        choices=Channel.choices,
        default=Channel.IN_APP,
        db_index=True,
    )

    priority = models.CharField(
        max_length=30,
        choices=Priority.choices,
        default=Priority.NORMAL,
        db_index=True,
    )

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    # Optional link to related object.
    # Example:
    # related_object_type = "order"
    # related_object_id = "15"
    related_object_type = models.CharField(max_length=80, blank=True)
    related_object_id = models.CharField(max_length=80, blank=True)

    action_url = models.CharField(max_length=500, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read", "-created_at"]),
            models.Index(fields=["notification_type", "-created_at"]),
            models.Index(fields=["channel", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.title} → {self.user}"

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at", "updated_at"])

    def mark_as_unread(self):
        if self.is_read:
            self.is_read = False
            self.read_at = None
            self.save(update_fields=["is_read", "read_at", "updated_at"])


class NotificationPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preference",
    )

    muted_notification_types = models.JSONField(
        default=list,
        blank=True,
        help_text="List of muted notification types, for example: ['product', 'inventory']",
    )

    muted_channels = models.JSONField(
        default=list,
        blank=True,
        help_text="List of muted channels, for example: ['email', 'sms']",
    )

    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)
    in_app_enabled = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification Preference"
        verbose_name_plural = "Notification Preferences"

    def __str__(self):
        return f"Notification preferences for {self.user}"

    def is_notification_allowed(self, *, notification_type, channel):
        if notification_type in self.muted_notification_types:
            return False

        if channel in self.muted_channels:
            return False

        if channel == Notification.Channel.EMAIL and not self.email_enabled:
            return False

        if channel == Notification.Channel.SMS and not self.sms_enabled:
            return False

        if channel == Notification.Channel.PUSH and not self.push_enabled:
            return False

        if channel == Notification.Channel.IN_APP and not self.in_app_enabled:
            return False

        return True
