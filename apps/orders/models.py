import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.products.models import Product
from apps.inventory.models import Warehouse


class Cart(models.Model):
    """
    One active shopping cart for each user.
    Example: Sina has one cart.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cart",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cart"
        verbose_name_plural = "Carts"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Cart of {self.user.phone}"

    @property
    def total_items(self):
        """
        Total quantity of all items in cart.
        Example: 2 phones + 1 laptop = 3 items.
        """
        return sum(item.quantity for item in self.items.all())

    @property
    def subtotal(self):
        """
        Cart price before discount, shipping, and tax.
        """
        total = Decimal("0")

        for item in self.items.select_related("product"):
            total += item.total_price

        return total

    def clear(self):
        """
        Remove all items from cart after checkout.
        """
        self.items.all().delete()


class CartItem(models.Model):
    """
    One product inside the cart.
    Example: iPhone 17 Pro Max x 2
    """

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="cart_items",
    )

    quantity = models.PositiveIntegerField(default=1)

    # Price snapshot inside cart.
    # If product price changes later, this cart item still has its own price.
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cart Item"
        verbose_name_plural = "Cart Items"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product"],
                name="unique_product_per_cart",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="cart_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="cart_item_unit_price_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    @property
    def total_price(self):
        """
        quantity * unit_price
        """
        return self.unit_price * self.quantity

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})

    def save(self, *args, **kwargs):
        self.clean()

        # If unit_price is empty, copy current product price.
        if not self.unit_price:
            self.unit_price = self.product.final_price

        super().save(*args, **kwargs)


class Order(models.Model):
    """
    Final order after checkout.

    Payment app will later update payment_status.
    Shipping app will later update shipping_status.
    """

    class StatusChoices(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending Payment"
        PAID = "paid", "Paid"
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    class PaymentStatusChoices(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    order_number = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )

    status = models.CharField(
        max_length=30,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING_PAYMENT,
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatusChoices.choices,
        default=PaymentStatusChoices.UNPAID,
    )

    # Money fields
    subtotal = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)

    # Address snapshot
    # We store address here because user address may change later.
    receiver_name = models.CharField(max_length=120)
    receiver_phone = models.CharField(max_length=20)
    province = models.CharField(max_length=80)
    city = models.CharField(max_length=80)
    address = models.TextField()
    postal_code = models.CharField(max_length=20)

    customer_note = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)

    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order_number"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["payment_status"]),
            models.Index(fields=["-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(subtotal__gte=0),
                name="order_subtotal_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(discount_amount__gte=0),
                name="order_discount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(shipping_cost__gte=0),
                name="order_shipping_cost_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(tax_amount__gte=0),
                name="order_tax_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=0),
                name="order_total_non_negative",
            ),
        ]

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()

        self.calculate_total()

        super().save(*args, **kwargs)

    @staticmethod
    def generate_order_number():
        """
        Generate readable order number.
        Example: ORD-20260507-A1B2C3
        """
        today = timezone.now().strftime("%Y%m%d")
        random_code = uuid.uuid4().hex[:6].upper()
        return f"ORD-{today}-{random_code}"

    def calculate_total(self):
        """
        total = subtotal - discount + shipping + tax
        """
        total = self.subtotal - self.discount_amount + self.shipping_cost + self.tax_amount

        if total < 0:
            total = Decimal("0")

        self.total_amount = total

    def mark_paid(self):
        """
        Mark order as paid.
        Payment app will use this later.
        """
        self.status = self.StatusChoices.PAID
        self.payment_status = self.PaymentStatusChoices.PAID
        self.paid_at = timezone.now()
        self.save(update_fields=["status", "payment_status", "paid_at", "total_amount", "updated_at"])

    def cancel(self):
        """
        Cancel order if it is not delivered.
        """
        if self.status == self.StatusChoices.DELIVERED:
            raise ValidationError("Delivered orders cannot be cancelled.")

        self.status = self.StatusChoices.CANCELLED
        self.cancelled_at = timezone.now()
        self.save(update_fields=["status", "cancelled_at", "total_amount", "updated_at"])


class OrderItem(models.Model):
    """
    One product inside an order.

    We store product_name, sku, and price as snapshot.
    Product data can change after order creation.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    # Optional warehouse reference.
    # Later checkout can reserve stock from a specific warehouse.
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )

    product_name = models.CharField(max_length=255)
    product_sku = models.CharField(max_length=100)

    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=0)
    total_price = models.DecimalField(max_digits=12, decimal_places=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="order_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="order_item_unit_price_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(total_price__gte=0),
                name="order_item_total_price_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"

    def save(self, *args, **kwargs):
        # Copy product data at order creation time.
        if not self.product_name:
            self.product_name = self.product.name

        if not self.product_sku:
            self.product_sku = self.product.sku

        self.total_price = self.unit_price * self.quantity

        super().save(*args, **kwargs)


class OrderStatusHistory(models.Model):
    """
    History of order status changes.

    Example:
    pending_payment -> paid
    paid -> processing
    processing -> shipped
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_history",
    )

    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30)

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_status_changes",
    )

    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Order Status History"
        verbose_name_plural = "Order Status Histories"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order.order_number}: {self.old_status} -> {self.new_status}"