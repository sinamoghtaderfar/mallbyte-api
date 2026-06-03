import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from apps.orders.models import Order, OrderStatusHistory


class Shipment(models.Model):
    """
    Shipment record for an order.

    One order can have one or more shipments.
    For now, we mostly use one shipment per order.
    """

    class CarrierChoices(models.TextChoices):
        POST = "post", "Post"
        DHL = "dhl", "DHL"
        TIPAX = "tipax", "Tipax"
        SNAPBOX = "snapbox", "Snapbox"
        OTHER = "other", "Other"

    class StatusChoices(models.TextChoices):
        PENDING = "pending", "Pending"
        READY_TO_SHIP = "ready_to_ship", "Ready To Ship"
        SHIPPED = "shipped", "Shipped"
        IN_TRANSIT = "in_transit", "In Transit"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out For Delivery"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        RETURNED = "returned", "Returned"
        CANCELLED = "cancelled", "Cancelled"

    shipment_number = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="shipments",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="shipments",
    )

    carrier = models.CharField(
        max_length=30,
        choices=CarrierChoices.choices,
        default=CarrierChoices.POST,
    )

    status = models.CharField(
        max_length=30,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
    )

    tracking_number = models.CharField(max_length=120, blank=True)
    tracking_url = models.URLField(blank=True)

    shipping_cost = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
    )

    # Address snapshot copied from order.
    receiver_name = models.CharField(max_length=120)
    receiver_phone = models.CharField(max_length=20)
    province = models.CharField(max_length=80)
    city = models.CharField(max_length=80)
    address = models.TextField()
    postal_code = models.CharField(max_length=20)

    notes = models.TextField(blank=True)

    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_shipments",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shipment"
        verbose_name_plural = "Shipments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["shipment_number"]),
            models.Index(fields=["order", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["carrier"]),
            models.Index(fields=["status"]),
            models.Index(fields=["tracking_number"]),
            models.Index(fields=["-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(shipping_cost__gte=0),
                name="shipment_shipping_cost_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.shipment_number} - {self.status}"

    def save(self, *args, **kwargs):
        if not self.shipment_number:
            self.shipment_number = self.generate_shipment_number()

        super().save(*args, **kwargs)

    @staticmethod
    def generate_shipment_number():
        """
        Generate readable shipment number.
        Example: SHP-20260527-A1B2C3
        """
        today = timezone.now().strftime("%Y%m%d")
        random_code = uuid.uuid4().hex[:6].upper()
        return f"SHP-{today}-{random_code}"

    @classmethod
    def create_from_order(cls, order, created_by=None, carrier=None):
        """
        Create shipment from a paid order.

        Address is copied from order because order address
        should stay unchanged even if user changes profile later.
        """

        if order.status != Order.StatusChoices.PAID:
            raise ValidationError("Shipment can be created only for paid orders.")

        shipment = cls.objects.create(
            order=order,
            user=order.user,
            carrier=carrier or cls.CarrierChoices.POST,
            shipping_cost=order.shipping_cost,
            receiver_name=order.receiver_name,
            receiver_phone=order.receiver_phone,
            province=order.province,
            city=order.city,
            address=order.address,
            postal_code=order.postal_code,
            created_by=created_by,
        )

        ShipmentEvent.objects.create(
            shipment=shipment,
            old_status="",
            new_status=shipment.status,
            message="Shipment created from paid order.",
            created_by=created_by,
        )

        return shipment

    def mark_ready(self, user=None, note=""):
        """
        Mark shipment as ready to ship.
        """

        with transaction.atomic():
            shipment = Shipment.objects.select_for_update().get(pk=self.pk)

            if shipment.status != self.StatusChoices.PENDING:
                raise ValidationError("Only pending shipments can be marked as ready.")

            old_status = shipment.status
            shipment.status = self.StatusChoices.READY_TO_SHIP
            shipment.save(update_fields=["status", "updated_at"])

            ShipmentEvent.objects.create(
                shipment=shipment,
                old_status=old_status,
                new_status=shipment.status,
                message=note or "Shipment is ready to ship.",
                created_by=user,
            )

            self.status = shipment.status

        return self

    def mark_shipped(self, tracking_number="", tracking_url="", user=None, note=""):
        """
        Mark shipment as shipped.

        This also changes order status to SHIPPED.
        """

        with transaction.atomic():
            shipment = Shipment.objects.select_for_update().get(pk=self.pk)

            if shipment.status not in [
                self.StatusChoices.PENDING,
                self.StatusChoices.READY_TO_SHIP,
            ]:
                raise ValidationError("Shipment cannot be marked as shipped from this status.")

            old_status = shipment.status

            shipment.status = self.StatusChoices.SHIPPED
            shipment.tracking_number = tracking_number
            shipment.tracking_url = tracking_url
            shipment.shipped_at = timezone.now()
            shipment.save(
                update_fields=[
                    "status",
                    "tracking_number",
                    "tracking_url",
                    "shipped_at",
                    "updated_at",
                ]
            )

            order = Order.objects.select_for_update().get(pk=shipment.order_id)
            old_order_status = order.status
            order.status = Order.StatusChoices.SHIPPED
            order.save(update_fields=["status", "total_amount", "updated_at"])

            ShipmentEvent.objects.create(
                shipment=shipment,
                old_status=old_status,
                new_status=shipment.status,
                message=note or "Shipment marked as shipped.",
                created_by=user,
            )

            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_order_status,
                new_status=order.status,
                changed_by=user,
                note=f"Shipment shipped: {shipment.shipment_number}",
            )

            self.status = shipment.status
            self.tracking_number = shipment.tracking_number
            self.tracking_url = shipment.tracking_url
            self.shipped_at = shipment.shipped_at

        return self

    def mark_delivered(self, user=None, note=""):
        """
        Mark shipment as delivered.

        This also changes order status to DELIVERED.
        """

        with transaction.atomic():
            shipment = Shipment.objects.select_for_update().get(pk=self.pk)

            if shipment.status not in [
                self.StatusChoices.SHIPPED,
                self.StatusChoices.IN_TRANSIT,
                self.StatusChoices.OUT_FOR_DELIVERY,
            ]:
                raise ValidationError("Shipment cannot be delivered from this status.")

            old_status = shipment.status

            shipment.status = self.StatusChoices.DELIVERED
            shipment.delivered_at = timezone.now()
            shipment.save(update_fields=["status", "delivered_at", "updated_at"])

            order = Order.objects.select_for_update().get(pk=shipment.order_id)
            old_order_status = order.status
            order.status = Order.StatusChoices.DELIVERED
            order.delivered_at = shipment.delivered_at
            order.save(update_fields=["status", "delivered_at", "total_amount", "updated_at"])

            ShipmentEvent.objects.create(
                shipment=shipment,
                old_status=old_status,
                new_status=shipment.status,
                message=note or "Shipment delivered.",
                created_by=user,
            )

            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_order_status,
                new_status=order.status,
                changed_by=user,
                note=f"Shipment delivered: {shipment.shipment_number}",
            )

            self.status = shipment.status
            self.delivered_at = shipment.delivered_at

        return self

    def cancel(self, user=None, note=""):
        """
        Cancel shipment.

        Delivered shipments cannot be cancelled.
        """

        with transaction.atomic():
            shipment = Shipment.objects.select_for_update().get(pk=self.pk)

            if shipment.status == self.StatusChoices.DELIVERED:
                raise ValidationError("Delivered shipment cannot be cancelled.")

            if shipment.status == self.StatusChoices.CANCELLED:
                raise ValidationError("Shipment is already cancelled.")

            old_status = shipment.status

            shipment.status = self.StatusChoices.CANCELLED
            shipment.cancelled_at = timezone.now()
            shipment.save(update_fields=["status", "cancelled_at", "updated_at"])

            ShipmentEvent.objects.create(
                shipment=shipment,
                old_status=old_status,
                new_status=shipment.status,
                message=note or "Shipment cancelled.",
                created_by=user,
            )

            self.status = shipment.status
            self.cancelled_at = shipment.cancelled_at

        return self


class ShipmentEvent(models.Model):
    """
    History/log of shipment status changes.
    """

    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name="events",
    )

    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30)

    message = models.TextField(blank=True)

    data = models.JSONField(
        default=dict,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shipment_events",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Shipment Event"
        verbose_name_plural = "Shipment Events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["shipment", "-created_at"]),
            models.Index(fields=["new_status"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.shipment.shipment_number}: {self.old_status} -> {self.new_status}"