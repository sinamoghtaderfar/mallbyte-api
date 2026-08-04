import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from apps.orders.models import Order
from apps.products.models import Product
from apps.returns.models import ReturnRequest

class SupportTag(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    color = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional UI color, for example: #FFAA00",
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Support Tag"
        verbose_name_plural = "Support Tags"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1

            while SupportTag.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug

        super().save(*args, **kwargs)
class SupportTicket(models.Model):
    class StatusChoices(models.TextChoices):
        OPEN = "open", "Open"
        PENDING = "pending", "Pending"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class PriorityChoices(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class CategoryChoices(models.TextChoices):
        ORDER = "order", "Order"
        PAYMENT = "payment", "Payment"
        SHIPPING = "shipping", "Shipping"
        RETURN = "return", "Return"
        PRODUCT = "product", "Product"
        ACCOUNT = "account", "Account"
        OTHER = "other", "Other"

    ticket_number = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
        db_index=True,
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_tickets",
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_support_tickets",
    )

    subject = models.CharField(max_length=255)

    category = models.CharField(
        max_length=30,
        choices=CategoryChoices.choices,
        default=CategoryChoices.OTHER,
        db_index=True,
    )

    priority = models.CharField(
        max_length=30,
        choices=PriorityChoices.choices,
        default=PriorityChoices.NORMAL,
        db_index=True,
    )

    status = models.CharField(
        max_length=30,
        choices=StatusChoices.choices,
        default=StatusChoices.OPEN,
        db_index=True,
    )
    
    tags = models.ManyToManyField(
        SupportTag,
        related_name="tickets",
        blank=True,
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )

    return_request = models.ForeignKey(
        ReturnRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )

    last_message_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Support Ticket"
        verbose_name_plural = "Support Tickets"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["customer", "-created_at"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["category", "status"]),
        ]

    def __str__(self):
        return f"{self.ticket_number} - {self.subject}"

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            date_part = timezone.now().strftime("%Y%m%d")
            unique_part = uuid.uuid4().hex[:8].upper()
            self.ticket_number = f"SUP-{date_part}-{unique_part}"

        super().save(*args, **kwargs)

    def mark_resolved(self):
        self.status = self.StatusChoices.RESOLVED
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_at", "updated_at"])

    def close(self):
        self.status = self.StatusChoices.CLOSED
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "closed_at", "updated_at"])

    def reopen(self):
        self.status = self.StatusChoices.OPEN
        self.resolved_at = None
        self.closed_at = None
        self.save(
            update_fields=[
                "status",
                "resolved_at",
                "closed_at",
                "updated_at",
            ]
        )


class TicketMessage(models.Model):
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_messages",
    )

    message = models.TextField()

    is_internal_note = models.BooleanField(
        default=False,
        help_text="Internal notes are visible only to staff/admin users.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ticket Message"
        verbose_name_plural = "Ticket Messages"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["ticket", "created_at"]),
            models.Index(fields=["sender", "-created_at"]),
            models.Index(fields=["is_internal_note"]),
        ]

    def __str__(self):
        return f"Message on {self.ticket.ticket_number} by {self.sender}"
    
class TicketAttachment(models.Model):
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    message = models.ForeignKey(
        TicketMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_attachments",
    )

    file = models.FileField(upload_to="support/attachments/")
    original_filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveBigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ticket Attachment"
        verbose_name_plural = "Ticket Attachments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ticket", "-created_at"]),
            models.Index(fields=["uploaded_by", "-created_at"]),
        ]

    def __str__(self):
        return f"Attachment for {self.ticket.ticket_number}"

    def save(self, *args, **kwargs):
        if self.file:
            if not self.original_filename:
                self.original_filename = os.path.basename(self.file.name)

            if not self.size and hasattr(self.file, "size"):
                self.size = self.file.size

        super().save(*args, **kwargs)


class TicketAuditLog(models.Model):
    class ActionChoices(models.TextChoices):
        CREATED = "created", "Created"
        REPLIED = "replied", "Replied"
        INTERNAL_NOTE_CREATED = "internal_note_created", "Internal Note Created"
        ASSIGNED = "assigned", "Assigned"
        STATUS_CHANGED = "status_changed", "Status Changed"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"
        REOPENED = "reopened", "Reopened"
        ATTACHMENT_ADDED = "attachment_added", "Attachment Added"
        TAG_ADDED = "tag_added", "Tag Added"
        TAG_REMOVED = "tag_removed", "Tag Removed"

    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_audit_logs",
    )

    action = models.CharField(
        max_length=40,
        choices=ActionChoices.choices,
        db_index=True,
    )

    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ticket Audit Log"
        verbose_name_plural = "Ticket Audit Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ticket", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.ticket.ticket_number} - {self.action}"

    @classmethod
    def log(cls, *, ticket, actor=None, action, description="", metadata=None):
        return cls.objects.create(
            ticket=ticket,
            actor=actor,
            action=action,
            description=description,
            metadata=metadata or {},
        )