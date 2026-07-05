import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def return_file_upload_path(instance, filename):
    request_number = "pending"

    if instance.return_request_id and instance.return_request.request_number:
        request_number = instance.return_request.request_number

    return f"returns/{request_number}/{filename}"


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class ReturnRequest(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Submitted")
        UNDER_REVIEW = "under_review", _("Under review")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        WAITING_FOR_ITEM = "waiting_for_item", _("Waiting for returned item")
        ITEM_RECEIVED = "item_received", _("Item received")
        INSPECTING = "inspecting", _("Inspecting")
        REFUND_PENDING = "refund_pending", _("Refund pending")
        REFUNDED = "refunded", _("Refunded")
        REPLACED = "replaced", _("Replaced")
        CANCELLED = "cancelled", _("Cancelled")
        CLOSED = "closed", _("Closed")

    class Reason(models.TextChoices):
        DAMAGED = "damaged", _("Damaged item")
        WRONG_ITEM = "wrong_item", _("Wrong item")
        DEFECTIVE = "defective", _("Defective")
        NOT_AS_DESCRIBED = "not_as_described", _("Not as described")
        SIZE_OR_FIT = "size_or_fit", _("Size or fit issue")
        CHANGED_MIND = "changed_mind", _("Changed mind")
        LATE_DELIVERY = "late_delivery", _("Late delivery")
        OTHER = "other", _("Other")

    class RequestedResolution(models.TextChoices):
        REFUND = "refund", _("Refund")
        REPLACEMENT = "replacement", _("Replacement")
        STORE_CREDIT = "store_credit", _("Store credit")
        REPAIR = "repair", _("Repair")
        OTHER = "other", _("Other")

    class RefundMethod(models.TextChoices):
        ORIGINAL_PAYMENT = "original_payment", _("Original payment method")
        STORE_CREDIT = "store_credit", _("Store credit")
        MANUAL = "manual", _("Manual refund")
        NONE = "none", _("No refund")

    request_number = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        db_index=True,
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="return_requests",
    )

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="return_requests",
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.SUBMITTED,
        db_index=True,
    )

    reason = models.CharField(
        max_length=32,
        choices=Reason.choices,
        default=Reason.OTHER,
    )

    requested_resolution = models.CharField(
        max_length=32,
        choices=RequestedResolution.choices,
        default=RequestedResolution.REFUND,
    )

    refund_method = models.CharField(
        max_length=32,
        choices=RefundMethod.choices,
        default=RefundMethod.ORIGINAL_PAYMENT,
    )

    customer_note = models.TextField(blank=True)
    internal_note = models.TextField(blank=True)

    total_requested_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    total_approved_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_return_requests",
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="return_status_created_idx"),
            models.Index(fields=["customer", "-created_at"], name="return_customer_created_idx"),
            models.Index(fields=["order"], name="return_order_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_requested_amount__gte=0),
                name="return_total_requested_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(total_approved_amount__gte=0),
                name="return_total_approved_non_negative",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.request_number:
            today = timezone.now().strftime("%Y%m%d")
            unique_part = uuid.uuid4().hex[:8].upper()
            self.request_number = f"RMA-{today}-{unique_part}"

        super().save(*args, **kwargs)

    def mark_reviewed(self, user):
        self.reviewed_by = user
        self.reviewed_at = timezone.now()

    def mark_closed(self):
        self.status = self.Status.CLOSED
        self.closed_at = timezone.now()

    def __str__(self):
        return f"{self.request_number} - {self.get_status_display()}"


class ReturnItem(TimeStampedModel):
    class ItemCondition(models.TextChoices):
        NEW = "new", _("New")
        OPENED = "opened", _("Opened")
        USED = "used", _("Used")
        DAMAGED = "damaged", _("Damaged")
        UNKNOWN = "unknown", _("Unknown")

    class ItemStatus(models.TextChoices):
        REQUESTED = "requested", _("Requested")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        RECEIVED = "received", _("Received")
        ACCEPTED = "accepted", _("Accepted")
        REFUNDED = "refunded", _("Refunded")
        REPLACED = "replaced", _("Replaced")

    return_request = models.ForeignKey(
        ReturnRequest,
        on_delete=models.CASCADE,
        related_name="items",
    )

    order_item = models.ForeignKey(
        "orders.OrderItem",
        on_delete=models.PROTECT,
        related_name="return_items",
    )

    quantity = models.PositiveIntegerField(default=1)

    reason = models.CharField(
        max_length=32,
        choices=ReturnRequest.Reason.choices,
        default=ReturnRequest.Reason.OTHER,
    )

    condition = models.CharField(
        max_length=32,
        choices=ItemCondition.choices,
        default=ItemCondition.UNKNOWN,
    )

    status = models.CharField(
        max_length=32,
        choices=ItemStatus.choices,
        default=ItemStatus.REQUESTED,
        db_index=True,
    )

    customer_note = models.TextField(blank=True)
    inspection_note = models.TextField(blank=True)

    requested_refund_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    approved_refund_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["return_request", "order_item"],
                name="unique_order_item_per_return_request",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="return_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(requested_refund_amount__gte=0),
                name="return_item_requested_refund_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(approved_refund_amount__gte=0),
                name="return_item_approved_refund_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.return_request.request_number} - Item #{self.order_item_id}"


class ReturnAttachment(TimeStampedModel):
    class AttachmentType(models.TextChoices):
        PRODUCT_PHOTO = "product_photo", _("Product photo")
        DAMAGE_PHOTO = "damage_photo", _("Damage photo")
        RECEIPT = "receipt", _("Receipt")
        SHIPPING_LABEL = "shipping_label", _("Shipping label")
        OTHER = "other", _("Other")

    return_request = models.ForeignKey(
        ReturnRequest,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    return_item = models.ForeignKey(
        ReturnItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="return_attachments",
    )

    attachment_type = models.CharField(
        max_length=32,
        choices=AttachmentType.choices,
        default=AttachmentType.OTHER,
    )

    file = models.FileField(upload_to=return_file_upload_path)
    caption = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.return_request.request_number} - {self.get_attachment_type_display()}"


class ReturnShipment(TimeStampedModel):
    return_request = models.OneToOneField(
        ReturnRequest,
        on_delete=models.CASCADE,
        related_name="shipment",
    )

    carrier = models.CharField(max_length=100, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True, db_index=True)
    tracking_url = models.URLField(blank=True)

    shipping_label = models.FileField(
        upload_to=return_file_upload_path,
        blank=True,
        null=True,
    )

    shipped_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Shipment for {self.return_request.request_number}"


class ReturnStatusHistory(TimeStampedModel):
    return_request = models.ForeignKey(
        ReturnRequest,
        on_delete=models.CASCADE,
        related_name="status_history",
    )

    old_status = models.CharField(max_length=32, blank=True)
    new_status = models.CharField(max_length=32)

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="return_status_changes",
    )

    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["return_request", "-created_at"], name="return_history_request_idx"),
        ]

    def __str__(self):
        return f"{self.return_request.request_number}: {self.old_status} → {self.new_status}"