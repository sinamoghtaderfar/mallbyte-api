import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from apps.inventory.models import Stock, StockMovement
from apps.orders.models import Order


class Payment(models.Model):
    """
    Payment record for one order.

    One order can have multiple payment attempts.
    Example:
    - first payment failed
    - second payment succeeded
    """

    class ProviderChoices(models.TextChoices):
        MOCK = "mock", "Mock Payment"
        CASH_ON_DELIVERY = "cash_on_delivery", "Cash on Delivery"
        ZARINPAL = "zarinpal", "Zarinpal"
        STRIPE = "stripe", "Stripe"

    class StatusChoices(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    payment_number = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    provider = models.CharField(
        max_length=30,
        choices=ProviderChoices.choices,
        default=ProviderChoices.MOCK,
    )

    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
    )

    currency = models.CharField(
        max_length=10,
        default="IRR",
    )

    # ID returned by external payment gateway.
    # Example: Stripe payment intent id, Zarinpal authority, etc.
    gateway_reference = models.CharField(
        max_length=255,
        blank=True,
    )

    # Extra raw data from gateway.
    gateway_response = models.JSONField(
        default=dict,
        blank=True,
    )

    failure_reason = models.TextField(blank=True)

    paid_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payments",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payment_number"]),
            models.Index(fields=["order", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["provider"]),
            models.Index(fields=["status"]),
            models.Index(fields=["-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="payment_amount_positive",
            ),
        ]

    def __str__(self):
        return f"{self.payment_number} - {self.status}"

    def save(self, *args, **kwargs):
        if not self.payment_number:
            self.payment_number = self.generate_payment_number()

        super().save(*args, **kwargs)

    @staticmethod
    def generate_payment_number():
        """
        Generate readable payment number.
        Example: PAY-20260514-A1B2C3
        """
        today = timezone.now().strftime("%Y%m%d")
        random_code = uuid.uuid4().hex[:6].upper()
        return f"PAY-{today}-{random_code}"

    def mark_success(self, gateway_reference="", gateway_response=None):
        """
        Mark payment as successful.

        Important:
        - Order becomes paid.
        - Reserved stock becomes real sale movement.
        """

        if gateway_response is None:
            gateway_response = {}

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=self.pk)

            if payment.status == self.StatusChoices.SUCCESS:
                raise ValidationError("Payment is already successful.")

            if payment.status in [
                self.StatusChoices.CANCELLED,
                self.StatusChoices.REFUNDED,
            ]:
                raise ValidationError("Cancelled or refunded payment cannot be marked as success.")

            order = Order.objects.select_for_update().get(pk=payment.order_id)

            if order.status == Order.StatusChoices.CANCELLED:
                raise ValidationError("Cannot pay a cancelled order.")

            # Convert reserved stock into real sale movement.
            for item in order.items.select_related("product", "warehouse"):
                if not item.warehouse_id:
                    continue

                stock = Stock.objects.select_for_update().get(
                    product=item.product,
                    warehouse=item.warehouse,
                )

                # First release reserved quantity.
                stock.release_reservation(
                    quantity=item.quantity,
                    user=payment.user,
                )

                # Then reduce actual stock with SALE movement.
                StockMovement.objects.create(
                    product=item.product,
                    warehouse=item.warehouse,
                    movement_type=StockMovement.MovementType.SALE,
                    quantity=-item.quantity,
                    reference_id=f"payment:{payment.id}",
                    reason=f"Order paid: {order.order_number}",
                    created_by=payment.user,
                    notes=f"Payment success: {payment.payment_number}",
                )

            payment.status = self.StatusChoices.SUCCESS
            payment.gateway_reference = gateway_reference
            payment.gateway_response = gateway_response
            payment.paid_at = timezone.now()
            payment.save(
                update_fields=[
                    "status",
                    "gateway_reference",
                    "gateway_response",
                    "paid_at",
                    "updated_at",
                ]
            )

            order.mark_paid()

            self.status = payment.status
            self.gateway_reference = payment.gateway_reference
            self.gateway_response = payment.gateway_response
            self.paid_at = payment.paid_at

        return self

    def mark_failed(self, reason="", gateway_response=None):
        """
        Mark payment as failed.
        Reserved stock stays reserved for now.
        User can try payment again.
        """

        if gateway_response is None:
            gateway_response = {}

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=self.pk)

            if payment.status == self.StatusChoices.SUCCESS:
                raise ValidationError("Successful payment cannot be marked as failed.")

            payment.status = self.StatusChoices.FAILED
            payment.failure_reason = reason
            payment.gateway_response = gateway_response
            payment.failed_at = timezone.now()
            payment.save(
                update_fields=[
                    "status",
                    "failure_reason",
                    "gateway_response",
                    "failed_at",
                    "updated_at",
                ]
            )

            self.status = payment.status
            self.failure_reason = payment.failure_reason
            self.failed_at = payment.failed_at

        return self

    def cancel(self, reason=""):
        """
        Cancel a pending payment.

        This does not cancel the order.
        Order cancellation is handled in orders app.
        """

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=self.pk)

            if payment.status == self.StatusChoices.SUCCESS:
                raise ValidationError("Successful payment cannot be cancelled.")

            if payment.status == self.StatusChoices.REFUNDED:
                raise ValidationError("Refunded payment cannot be cancelled.")

            payment.status = self.StatusChoices.CANCELLED
            payment.failure_reason = reason
            payment.cancelled_at = timezone.now()
            payment.save(
                update_fields=[
                    "status",
                    "failure_reason",
                    "cancelled_at",
                    "updated_at",
                ]
            )

            self.status = payment.status
            self.failure_reason = payment.failure_reason
            self.cancelled_at = payment.cancelled_at

        return self


class PaymentEvent(models.Model):
    """
    History/log of payment changes.

    Useful for debugging gateway callbacks.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="events",
    )

    event_type = models.CharField(max_length=50)

    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20)

    message = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_events",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Payment Event"
        verbose_name_plural = "Payment Events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payment", "-created_at"]),
            models.Index(fields=["event_type"]),
            models.Index(fields=["new_status"]),
        ]

    def __str__(self):
        return f"{self.payment.payment_number}: {self.event_type}"