# apps/inventory/models.py

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.products.models import Product

User = get_user_model()


class Warehouse(models.Model):
    """Warehouse model - where products are stored."""

    class TypeChoices(models.TextChoices):
        MAIN = "main", "Main Warehouse"
        BRANCH = "branch", "Branch Warehouse"
        THIRD_PARTY = "third_party", "Third Party Warehouse"

    name = models.CharField(max_length=100, unique=True, verbose_name="Warehouse Name")
    code = models.CharField(max_length=20, unique=True, verbose_name="Warehouse Code")
    type = models.CharField(
        max_length=20,
        choices=TypeChoices.choices,
        default=TypeChoices.BRANCH,
        verbose_name="Warehouse Type",
    )

    # Address fields
    province = models.CharField(max_length=50, verbose_name="Province")
    city = models.CharField(max_length=50, verbose_name="City")
    address = models.TextField(verbose_name="Full Address")
    postal_code = models.CharField(max_length=10, verbose_name="Postal Code")

    # Contact info
    phone = models.CharField(max_length=15, verbose_name="Phone Number")
    email = models.EmailField(blank=True, verbose_name="Email")
    manager_name = models.CharField(max_length=100, verbose_name="Manager Name")
    manager_phone = models.CharField(max_length=15, verbose_name="Manager Phone")

    # Status
    is_active = models.BooleanField(default=True, verbose_name="Is Active")

    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_warehouses",
        verbose_name="Created By",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Warehouse"
        verbose_name_plural = "Warehouses"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["city"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.upper().strip()
        super().save(*args, **kwargs)


class Stock(models.Model):
    """Current product stock in each warehouse."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_items",
        verbose_name="Product",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="stock_items",
        verbose_name="Warehouse",
    )

    quantity = models.PositiveIntegerField(default=0, verbose_name="Current Quantity")
    reserved_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="Reserved Quantity",
        help_text="Quantity reserved for pending orders.",
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        verbose_name="Low Stock Alert Threshold",
    )

    # Location inside warehouse
    aisle = models.CharField(max_length=20, blank=True, verbose_name="Aisle")
    shelf = models.CharField(max_length=20, blank=True, verbose_name="Shelf")
    bin_code = models.CharField(max_length=20, blank=True, verbose_name="Bin Code")

    # Metadata
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_updates",
        verbose_name="Updated By",
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Stock"
        verbose_name_plural = "Stock Items"
        ordering = ["product__name", "warehouse__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "warehouse"],
                name="unique_stock_per_product_warehouse",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=0),
                name="stock_quantity_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__gte=0),
                name="stock_reserved_quantity_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__lte=F("quantity")),
                name="stock_reserved_lte_quantity",
            ),
        ]
        indexes = [
            models.Index(fields=["product", "warehouse"]),
            models.Index(fields=["warehouse"]),
            models.Index(fields=["quantity"]),
            models.Index(fields=["last_updated"]),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.warehouse.name}: {self.quantity}"

    @property
    def available_quantity(self):
        """Available stock = total stock - reserved stock."""
        return self.quantity - self.reserved_quantity

    @property
    def is_low_stock(self):
        """Check whether available stock is below or equal to threshold."""
        return self.available_quantity <= self.low_stock_threshold

    def clean(self):
        if self.reserved_quantity > self.quantity:
            raise ValidationError(
                {"reserved_quantity": "Reserved quantity cannot be greater than total quantity."}
            )

    def reserve(self, quantity, user=None):
        """Reserve stock for a pending order."""
        if quantity <= 0:
            raise ValidationError("Reserve quantity must be greater than zero.")

        with transaction.atomic():
            stock = Stock.objects.select_for_update().get(pk=self.pk)

            if stock.available_quantity < quantity:
                raise ValidationError("Not enough available stock to reserve.")

            stock.reserved_quantity += quantity
            stock.updated_by = user
            stock.save(update_fields=["reserved_quantity", "updated_by", "last_updated"])

            self.reserved_quantity = stock.reserved_quantity
            self.quantity = stock.quantity

        return self

    def release_reservation(self, quantity, user=None):
        """Release previously reserved stock."""
        if quantity <= 0:
            raise ValidationError("Release quantity must be greater than zero.")

        with transaction.atomic():
            stock = Stock.objects.select_for_update().get(pk=self.pk)

            if stock.reserved_quantity < quantity:
                raise ValidationError("Cannot release more than reserved quantity.")

            stock.reserved_quantity -= quantity
            stock.updated_by = user
            stock.save(update_fields=["reserved_quantity", "updated_by", "last_updated"])

            self.reserved_quantity = stock.reserved_quantity
            self.quantity = stock.quantity

        return self


class StockMovement(models.Model):
    """Stock movement history - every inventory change must be recorded here."""

    class MovementType(models.TextChoices):
        PURCHASE = "purchase", "Purchase Order"
        SALE = "sale", "Customer Order"
        RETURN = "return", "Customer Return"
        TRANSFER_IN = "transfer_in", "Transfer In"
        TRANSFER_OUT = "transfer_out", "Transfer Out"
        ADJUSTMENT = "adjustment", "Stock Adjustment"
        DAMAGED = "damaged", "Damaged Goods"

    INCREASE_TYPES = {
        MovementType.PURCHASE,
        MovementType.RETURN,
        MovementType.TRANSFER_IN,
    }

    DECREASE_TYPES = {
        MovementType.SALE,
        MovementType.TRANSFER_OUT,
        MovementType.DAMAGED,
    }

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_movements",
        verbose_name="Product",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="stock_movements",
        verbose_name="Warehouse",
    )
    movement_type = models.CharField(
        max_length=20,
        choices=MovementType.choices,
        verbose_name="Movement Type",
    )

    quantity = models.IntegerField(
        verbose_name="Quantity",
        help_text="Positive = stock in, negative = stock out.",
    )

    reference_id = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Reference ID",
        help_text="Order ID, Transfer ID, Purchase ID, etc.",
    )
    reason = models.TextField(blank=True, verbose_name="Reason")

    # Audit fields
    before_quantity = models.PositiveIntegerField(default=0, verbose_name="Before Quantity")
    after_quantity = models.PositiveIntegerField(default=0, verbose_name="After Quantity")

    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
        verbose_name="Created By",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Stock Movement"
        verbose_name_plural = "Stock Movements"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "warehouse"]),
            models.Index(fields=["movement_type"]),
            models.Index(fields=["reference_id"]),
            models.Index(fields=["-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(quantity=0),
                name="stock_movement_quantity_not_zero",
            ),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()}: {self.product.name} ({self.quantity}) at {self.warehouse.name}"

    def clean(self):
        if self.quantity == 0:
            raise ValidationError({"quantity": "Quantity cannot be zero."})

        if self.movement_type in self.INCREASE_TYPES and self.quantity < 0:
            raise ValidationError(
                {"quantity": f"{self.get_movement_type_display()} must have a positive quantity."}
            )

        if self.movement_type in self.DECREASE_TYPES and self.quantity > 0:
            raise ValidationError(
                {"quantity": f"{self.get_movement_type_display()} must have a negative quantity."}
            )

    def _validate_immutable_fields(self):
        """Prevent editing important fields after movement creation."""
        if not self.pk:
            return

        old = StockMovement.objects.get(pk=self.pk)

        immutable_fields = [
            "product_id",
            "warehouse_id",
            "movement_type",
            "quantity",
            "before_quantity",
            "after_quantity",
        ]

        for field in immutable_fields:
            if getattr(old, field) != getattr(self, field):
                raise ValidationError(
                    "Stock movements are immutable. Create a new movement instead of editing this one."
                )

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        self.clean()

        if not is_new:
            self._validate_immutable_fields()
            super().save(*args, **kwargs)
            return

        with transaction.atomic():
            stock, created = Stock.objects.select_for_update().get_or_create(
                product=self.product,
                warehouse=self.warehouse,
                defaults={
                    "quantity": 0,
                    "reserved_quantity": 0,
                    "updated_by": self.created_by,
                },
            )

            self.before_quantity = stock.quantity
            new_quantity = stock.quantity + self.quantity

            if new_quantity < 0:
                raise ValidationError("Not enough stock for this movement.")

            if stock.reserved_quantity > new_quantity:
                raise ValidationError(
                    "This movement would make total stock lower than reserved stock."
                )

            stock.quantity = new_quantity
            stock.updated_by = self.created_by
            stock.save(update_fields=["quantity", "updated_by", "last_updated"])

            self.after_quantity = new_quantity

            super().save(*args, **kwargs)


class StockTransfer(models.Model):
    """Transfer stock between two warehouses."""

    class StatusChoices(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_TRANSIT = "in_transit", "In Transit"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    from_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="transfers_out",
        verbose_name="From Warehouse",
    )
    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="transfers_in",
        verbose_name="To Warehouse",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_transfers",
        verbose_name="Product",
    )
    quantity = models.PositiveIntegerField(verbose_name="Quantity")

    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
        verbose_name="Status",
    )

    # Tracking
    tracking_number = models.CharField(max_length=100, blank=True, verbose_name="Tracking Number")
    shipped_at = models.DateTimeField(null=True, blank=True, verbose_name="Shipped At")
    delivered_at = models.DateTimeField(null=True, blank=True, verbose_name="Delivered At")

    # Metadata
    reason = models.TextField(blank=True, verbose_name="Reason")
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfer_requests",
        verbose_name="Requested By",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_transfers",
        verbose_name="Approved By",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Stock Transfer"
        verbose_name_plural = "Stock Transfers"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product"]),
            models.Index(fields=["from_warehouse", "to_warehouse"]),
            models.Index(fields=["status"]),
            models.Index(fields=["-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="stock_transfer_quantity_positive",
            ),
            models.CheckConstraint(
                condition=~Q(from_warehouse=F("to_warehouse")),
                name="stock_transfer_different_warehouses",
            ),
        ]

    def __str__(self):
        return (
            f"Transfer {self.product.name}: "
            f"{self.from_warehouse.name} → {self.to_warehouse.name} ({self.quantity})"
        )

    def clean(self):
        if self.from_warehouse_id and self.to_warehouse_id:
            if self.from_warehouse_id == self.to_warehouse_id:
                raise ValidationError(
                    {"to_warehouse": "Source and destination warehouses cannot be the same."}
                )

        if self.quantity <= 0:
            raise ValidationError({"quantity": "Transfer quantity must be greater than zero."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def mark_in_transit(self, user=None, tracking_number=None):
        """Mark transfer as in transit."""
        with transaction.atomic():
            transfer = StockTransfer.objects.select_for_update().get(pk=self.pk)

            if transfer.status != self.StatusChoices.PENDING:
                raise ValidationError("Only pending transfers can be marked as in transit.")

            transfer.status = self.StatusChoices.IN_TRANSIT
            transfer.shipped_at = timezone.now()
            transfer.approved_by = user or transfer.approved_by

            if tracking_number:
                transfer.tracking_number = tracking_number

            transfer.save(
                update_fields=[
                    "status",
                    "shipped_at",
                    "approved_by",
                    "tracking_number",
                    "updated_at",
                ]
            )

            self.status = transfer.status
            self.shipped_at = transfer.shipped_at
            self.approved_by = transfer.approved_by
            self.tracking_number = transfer.tracking_number

        return self

    def complete(self, user=None):
        """
        Complete transfer and create two stock movements:
        1. transfer_out from source warehouse
        2. transfer_in to destination warehouse
        """
        with transaction.atomic():
            transfer = StockTransfer.objects.select_for_update().get(pk=self.pk)

            if transfer.status == self.StatusChoices.COMPLETED:
                raise ValidationError("This transfer is already completed.")

            if transfer.status == self.StatusChoices.CANCELLED:
                raise ValidationError("Cancelled transfers cannot be completed.")

            reference = f"transfer:{transfer.id}"

            StockMovement.objects.create(
                product=transfer.product,
                warehouse=transfer.from_warehouse,
                movement_type=StockMovement.MovementType.TRANSFER_OUT,
                quantity=-transfer.quantity,
                reference_id=reference,
                reason=transfer.reason,
                created_by=user,
                notes=f"Transfer out to {transfer.to_warehouse.name}",
            )

            StockMovement.objects.create(
                product=transfer.product,
                warehouse=transfer.to_warehouse,
                movement_type=StockMovement.MovementType.TRANSFER_IN,
                quantity=transfer.quantity,
                reference_id=reference,
                reason=transfer.reason,
                created_by=user,
                notes=f"Transfer in from {transfer.from_warehouse.name}",
            )

            transfer.status = self.StatusChoices.COMPLETED
            transfer.delivered_at = timezone.now()
            transfer.approved_by = user or transfer.approved_by
            transfer.save(
                update_fields=[
                    "status",
                    "delivered_at",
                    "approved_by",
                    "updated_at",
                ]
            )

            self.status = transfer.status
            self.delivered_at = transfer.delivered_at
            self.approved_by = transfer.approved_by

        return self

    def cancel(self):
        """Cancel transfer if it has not been completed."""
        with transaction.atomic():
            transfer = StockTransfer.objects.select_for_update().get(pk=self.pk)

            if transfer.status == self.StatusChoices.COMPLETED:
                raise ValidationError("Completed transfers cannot be cancelled.")

            transfer.status = self.StatusChoices.CANCELLED
            transfer.save(update_fields=["status", "updated_at"])

            self.status = transfer.status

        return self