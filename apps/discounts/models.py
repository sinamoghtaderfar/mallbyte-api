from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.orders.models import Cart, Order
from apps.products.models import Category, Product


class Discount(models.Model):
    """
    Discount/coupon model.

    Supports:
    - percentage discounts
    - fixed amount discounts
    - usage limits
    - date limits
    - minimum order amount
    - product/category targeting
    """

    class DiscountTypeChoices(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage"
        FIXED_AMOUNT = "fixed_amount", "Fixed Amount"

    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
    )

    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    discount_type = models.CharField(
        max_length=30,
        choices=DiscountTypeChoices.choices,
        default=DiscountTypeChoices.PERCENTAGE,
    )

    value = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        help_text="Percentage value or fixed amount depending on discount type.",
    )

    max_discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        help_text="Only useful for percentage discounts.",
    )

    min_order_amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        default=0,
    )

    usage_limit_total = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum total usage. Empty means unlimited.",
    )

    usage_limit_per_user = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum usage per user. Empty means unlimited.",
    )

    used_count = models.PositiveIntegerField(default=0)

    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    applicable_products = models.ManyToManyField(
        Product,
        blank=True,
        related_name="discounts",
    )

    applicable_categories = models.ManyToManyField(
        Category,
        blank=True,
        related_name="discounts",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_discounts",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Discount"
        verbose_name_plural = "Discounts"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["start_at", "end_at"]),
            models.Index(fields=["-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(value__gte=0),
                name="discount_value_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(min_order_amount__gte=0),
                name="discount_min_order_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(used_count__gte=0),
                name="discount_used_count_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.title}"

    def clean(self):
        if self.discount_type == self.DiscountTypeChoices.PERCENTAGE and self.value > 100:
            raise ValidationError({"value": "Percentage discount cannot be more than 100."})

        if self.end_at and self.start_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "End date must be after start date."})

        if self.max_discount_amount is not None and self.max_discount_amount < 0:
            raise ValidationError({"max_discount_amount": "Maximum discount amount cannot be negative."})

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return self.end_at is not None and timezone.now() > self.end_at

    @property
    def is_started(self):
        return self.start_at is None or timezone.now() >= self.start_at

    @property
    def has_total_usage_left(self):
        if self.usage_limit_total is None:
            return True

        return self.used_count < self.usage_limit_total

    def get_user_usage_count(self, user):
        if not user or not user.is_authenticated:
            return 0

        return self.usages.filter(user=user).count()

    def has_user_usage_left(self, user):
        if self.usage_limit_per_user is None:
            return True

        return self.get_user_usage_count(user) < self.usage_limit_per_user

    def get_eligible_subtotal(self, cart):
        """
        If no product/category targeting is configured,
        the whole cart subtotal is eligible.

        If targeting exists, only matching cart items are eligible.
        """

        if not isinstance(cart, Cart):
            raise ValidationError("Invalid cart.")

        product_ids = set(self.applicable_products.values_list("id", flat=True))
        category_ids = set(self.applicable_categories.values_list("id", flat=True))

        has_targeting = bool(product_ids or category_ids)

        if not has_targeting:
            return cart.subtotal

        eligible_subtotal = Decimal("0")

        for item in cart.items.select_related("product", "product__category"):
            product = item.product

            product_matches = product.id in product_ids
            category_matches = product.category_id in category_ids

            if product_matches or category_matches:
                eligible_subtotal += item.total_price

        return eligible_subtotal

    def calculate_discount_amount(self, cart):
        eligible_subtotal = self.get_eligible_subtotal(cart)

        if eligible_subtotal <= 0:
            return Decimal("0")

        if self.discount_type == self.DiscountTypeChoices.PERCENTAGE:
            discount_amount = eligible_subtotal * self.value / Decimal("100")

            if self.max_discount_amount is not None:
                discount_amount = min(discount_amount, self.max_discount_amount)

            return discount_amount

        if self.discount_type == self.DiscountTypeChoices.FIXED_AMOUNT:
            return min(self.value, eligible_subtotal)

        return Decimal("0")

    def validate_for_cart(self, user, cart):
        if not self.is_active:
            raise ValidationError("This discount is not active.")

        if not self.is_started:
            raise ValidationError("This discount has not started yet.")

        if self.is_expired:
            raise ValidationError("This discount has expired.")

        if not self.has_total_usage_left:
            raise ValidationError("This discount usage limit has been reached.")

        if not self.has_user_usage_left(user):
            raise ValidationError("You have already used this discount too many times.")

        if cart.subtotal < self.min_order_amount:
            raise ValidationError("Cart subtotal is lower than the minimum order amount.")

        discount_amount = self.calculate_discount_amount(cart)

        if discount_amount <= 0:
            raise ValidationError("This discount is not applicable to this cart.")

        return discount_amount


class DiscountUsage(models.Model):
    """
    Audit log for discount usage.

    One row is created when a discount is applied to an order.
    """

    discount = models.ForeignKey(
        Discount,
        on_delete=models.PROTECT,
        related_name="usages",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="discount_usages",
    )

    order = models.OneToOneField(
        Order,
        on_delete=models.PROTECT,
        related_name="discount_usage",
        null=True,
        blank=True,
    )

    code_snapshot = models.CharField(max_length=50)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Discount Usage"
        verbose_name_plural = "Discount Usages"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["code_snapshot"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["discount", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(discount_amount__gte=0),
                name="discount_usage_amount_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.code_snapshot} - {self.user}"