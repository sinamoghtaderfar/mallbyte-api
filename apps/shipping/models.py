import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from apps.orders.models import (
    Order,
    OrderStatusHistory,
    SellerOrderFulfillment,
    SellerOrderFulfillmentHistory,
)


class Shipment(models.Model):
    """A physical shipment; seller orders have one active shipment per seller."""

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

    shipment_number = models.CharField(max_length=40, unique=True, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="shipments")
    # Nullable to keep existing shipments and legacy orders usable.
    seller_fulfillment = models.ForeignKey(
        SellerOrderFulfillment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
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
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=0, default=0)

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
            models.Index(fields=["seller_fulfillment", "status"]),
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
            models.UniqueConstraint(
                fields=["seller_fulfillment"],
                condition=(
                    Q(seller_fulfillment__isnull=False)
                    & ~Q(status__in=["cancelled", "returned"])
                ),
                name="unique_active_shipment_per_seller_order",
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
        today = timezone.now().strftime("%Y%m%d")
        random_code = uuid.uuid4().hex[:6].upper()
        return f"SHP-{today}-{random_code}"

    @staticmethod
    def _ensure_paid_order(order):
        if order.payment_status != Order.PaymentStatusChoices.PAID or order.status in {
            Order.StatusChoices.PENDING_PAYMENT,
            Order.StatusChoices.CANCELLED,
            Order.StatusChoices.REFUNDED,
            Order.StatusChoices.DELIVERED,
        }:
            raise ValidationError("Shipment requires a paid, active order.")

    @classmethod
    def create_from_order(cls, order, created_by=None, carrier=None, seller=None):
        """Create a shipment for one seller, or a legacy order without items.

        `seller` can be a user instance or ID. It is required when an order
        contains products belonging to more than one seller.
        """
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            cls._ensure_paid_order(order)

            seller_ids = sorted(
                order.items.values_list("product__seller_id", flat=True).distinct()
            )
            seller_id = getattr(seller, "pk", seller)
            fulfillment = None

            if seller_ids:
                if seller_id is None:
                    if len(seller_ids) != 1:
                        raise ValidationError(
                            "Choose a seller for this multi-seller order."
                        )
                    seller_id = seller_ids[0]
                if seller_id not in seller_ids:
                    raise ValidationError("This seller has no items in the order.")
                (
                    fulfillment,
                    _,
                ) = SellerOrderFulfillment.objects.select_for_update().get_or_create(
                    order=order,
                    seller_id=seller_id,
                    defaults={"status": Order.StatusChoices.PAID},
                )
                active = cls.objects.filter(seller_fulfillment=fulfillment).exclude(
                    status__in=[cls.StatusChoices.CANCELLED, cls.StatusChoices.RETURNED]
                )
            else:
                if seller_id is not None:
                    raise ValidationError("This order has no seller items.")
                # Older tests/orders may have no OrderItem records.
                active = cls.objects.filter(order=order).exclude(
                    status__in=[cls.StatusChoices.CANCELLED, cls.StatusChoices.RETURNED]
                )

            # Do not mix existing order-level shipments with seller-specific ones.
            legacy_active = cls.objects.filter(
                order=order, seller_fulfillment__isnull=True
            ).exclude(
                status__in=[cls.StatusChoices.CANCELLED, cls.StatusChoices.RETURNED]
            )
            if active.exists() or legacy_active.exists():
                raise ValidationError("An active shipment already exists.")

            shipment = cls.objects.create(
                order=order,
                seller_fulfillment=fulfillment,
                user=order.user,
                carrier=carrier or cls.CarrierChoices.POST,
                # The order's shipping fee must not be counted once per seller.
                shipping_cost=order.shipping_cost if len(seller_ids) <= 1 else 0,
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

    @staticmethod
    def _set_seller_status(shipment, new_status, user, note):
        if not shipment.seller_fulfillment_id:
            return
        fulfillment = SellerOrderFulfillment.objects.select_for_update().get(
            pk=shipment.seller_fulfillment_id
        )
        if fulfillment.status == new_status:
            return
        old_status = fulfillment.status
        fulfillment.status = new_status
        fulfillment.save(update_fields=["status", "updated_at"])
        SellerOrderFulfillmentHistory.objects.create(
            fulfillment=fulfillment,
            old_status=old_status,
            new_status=new_status,
            changed_by=user,
            note=note,
        )

    @staticmethod
    def _sync_order_status(order, fallback_status, user, note, timestamp=None):
        """The whole order ships only after all sellers have shipped."""
        seller_statuses = list(
            order.seller_fulfillments.values_list("status", flat=True)
        )
        if not seller_statuses:
            # Preserve the former behavior for orders with no seller items.
            new_status = fallback_status
        elif all(s == Order.StatusChoices.DELIVERED for s in seller_statuses):
            new_status = Order.StatusChoices.DELIVERED
        elif all(
            s in {Order.StatusChoices.SHIPPED, Order.StatusChoices.DELIVERED}
            for s in seller_statuses
        ):
            new_status = Order.StatusChoices.SHIPPED
        elif any(
            s
            in {
                Order.StatusChoices.PROCESSING,
                Order.StatusChoices.SHIPPED,
                Order.StatusChoices.DELIVERED,
            }
            for s in seller_statuses
        ):
            new_status = Order.StatusChoices.PROCESSING
        else:
            new_status = Order.StatusChoices.PAID

        if new_status == order.status:
            return
        old_status = order.status
        order.status = new_status
        update_fields = ["status", "total_amount", "updated_at"]
        if new_status == Order.StatusChoices.DELIVERED:
            order.delivered_at = timestamp or timezone.now()
            update_fields.append("delivered_at")
        elif old_status == Order.StatusChoices.DELIVERED:
            order.delivered_at = None
            update_fields.append("delivered_at")
        order.save(update_fields=update_fields)
        OrderStatusHistory.objects.create(
            order=order,
            old_status=old_status,
            new_status=new_status,
            changed_by=user,
            note=note,
        )

    def mark_ready(self, user=None, note=""):
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=self.order_id)
            self._ensure_paid_order(order)
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
            self._set_seller_status(
                shipment,
                Order.StatusChoices.PROCESSING,
                user,
                note or f"Shipment ready: {shipment.shipment_number}",
            )
            self._sync_order_status(
                order,
                Order.StatusChoices.PROCESSING,
                user,
                f"Shipment ready: {shipment.shipment_number}",
            )
            self.status = shipment.status
        return self

    def mark_shipped(self, tracking_number="", tracking_url="", user=None, note=""):
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=self.order_id)
            self._ensure_paid_order(order)
            shipment = Shipment.objects.select_for_update().get(pk=self.pk)
            if shipment.status not in {
                self.StatusChoices.PENDING,
                self.StatusChoices.READY_TO_SHIP,
            }:
                raise ValidationError(
                    "Shipment cannot be marked as shipped from this status."
                )
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
            ShipmentEvent.objects.create(
                shipment=shipment,
                old_status=old_status,
                new_status=shipment.status,
                message=note or "Shipment marked as shipped.",
                created_by=user,
            )
            self._set_seller_status(
                shipment,
                Order.StatusChoices.SHIPPED,
                user,
                note or f"Shipment shipped: {shipment.shipment_number}",
            )
            self._sync_order_status(
                order,
                Order.StatusChoices.SHIPPED,
                user,
                f"Shipment shipped: {shipment.shipment_number}",
            )
            self.status = shipment.status
            self.tracking_number = shipment.tracking_number
            self.tracking_url = shipment.tracking_url
            self.shipped_at = shipment.shipped_at
        return self

    def mark_delivered(self, user=None, note=""):
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=self.order_id)
            self._ensure_paid_order(order)
            shipment = Shipment.objects.select_for_update().get(pk=self.pk)
            if shipment.status not in {
                self.StatusChoices.SHIPPED,
                self.StatusChoices.IN_TRANSIT,
                self.StatusChoices.OUT_FOR_DELIVERY,
            }:
                raise ValidationError("Shipment cannot be delivered from this status.")
            old_status = shipment.status
            shipment.status = self.StatusChoices.DELIVERED
            shipment.delivered_at = timezone.now()
            shipment.save(update_fields=["status", "delivered_at", "updated_at"])
            ShipmentEvent.objects.create(
                shipment=shipment,
                old_status=old_status,
                new_status=shipment.status,
                message=note or "Shipment delivered.",
                created_by=user,
            )
            self._set_seller_status(
                shipment,
                Order.StatusChoices.DELIVERED,
                user,
                note or f"Shipment delivered: {shipment.shipment_number}",
            )
            self._sync_order_status(
                order,
                Order.StatusChoices.DELIVERED,
                user,
                f"Shipment delivered: {shipment.shipment_number}",
                timestamp=shipment.delivered_at,
            )
            self.status = shipment.status
            self.delivered_at = shipment.delivered_at
        return self

    def cancel(self, user=None, note=""):
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=self.order_id)
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
            if shipment.seller_fulfillment_id:
                self._set_seller_status(
                    shipment,
                    Order.StatusChoices.PAID,
                    user,
                    note or f"Shipment cancelled: {shipment.shipment_number}",
                )
                self._sync_order_status(
                    order,
                    Order.StatusChoices.PAID,
                    user,
                    f"Shipment cancelled: {shipment.shipment_number}",
                )
            self.status = shipment.status
            self.cancelled_at = shipment.cancelled_at
        return self


class ShipmentEvent(models.Model):
    """History of changes to a physical shipment."""

    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name="events",
    )
    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30)
    message = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
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
        return (
            f"{self.shipment.shipment_number}: {self.old_status} -> {self.new_status}"
        )
