import hashlib
import json
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import Seller
from apps.discounts.services import apply_discount_to_order, validate_discount_for_cart
from apps.inventory.models import Stock
from apps.orders.checkout_policy import reservation_deadline, shipping_charge
from apps.orders.models import (
    Cart,
    CartItem,
    Order,
    OrderItem,
    OrderStatusHistory,
    SellerOrderFulfillment,
)
from apps.orders.services import create_order_notification
from apps.products.models import Product
from apps.rbac.commerce import can_view_all

# ============================================================
# Cart Item Serializer
# ============================================================


class CartItemSerializer(serializers.ModelSerializer):
    """
    Shows one item inside the cart.
    Example: Product A x 2
    """

    product_name = serializers.ReadOnlyField(source="product.name")
    product_sku = serializers.ReadOnlyField(source="product.sku")
    product_price = serializers.ReadOnlyField(source="product.final_price")
    available_stock = serializers.ReadOnlyField(source="product.available_stock")
    total_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=0,
        read_only=True,
    )

    class Meta:
        model = CartItem
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "product_price",
            "available_stock",
            "quantity",
            "unit_price",
            "total_price",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "unit_price",
            "total_price",
            "created_at",
            "updated_at",
        ]


# ============================================================
# Cart Serializer
# ============================================================


class CartSerializer(serializers.ModelSerializer):
    """
    Shows the user's cart with all items.
    """

    items = CartItemSerializer(many=True, read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    subtotal = serializers.DecimalField(
        max_digits=12,
        decimal_places=0,
        read_only=True,
    )

    class Meta:
        model = Cart
        fields = [
            "id",
            "user",
            "items",
            "total_items",
            "subtotal",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "items",
            "total_items",
            "subtotal",
            "created_at",
            "updated_at",
        ]


# ============================================================
# Add To Cart Serializer
# ============================================================


class AddToCartSerializer(serializers.Serializer):
    """
    Input serializer for adding product to cart.

    Input:
    {
        "product": 1,
        "quantity": 2
    }
    """

    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(is_active=True)
    )
    quantity = serializers.IntegerField(min_value=1)

    def validate_product(self, product):
        """
        Product must be approved and active.
        """
        if product.status != Product.StatusChoices.APPROVED:
            raise serializers.ValidationError("Product is not approved.")

        if not product.is_active:
            raise serializers.ValidationError("Product is not active.")

        return product

    def validate(self, attrs):
        """
        Check available stock before adding to cart.
        """
        product = attrs["product"]
        quantity = attrs["quantity"]

        if product.available_stock < quantity:
            raise serializers.ValidationError(
                {"quantity": "Not enough available stock."}
            )

        return attrs


# ============================================================
# Update Cart Item Serializer
# ============================================================


class UpdateCartItemSerializer(serializers.Serializer):
    """
    Input serializer for changing cart item quantity.

    Input:
    {
        "quantity": 3
    }
    """

    quantity = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        cart_item = self.context.get("cart_item")
        quantity = attrs["quantity"]

        if cart_item and cart_item.product.available_stock < quantity:
            raise serializers.ValidationError(
                {"quantity": "Not enough available stock."}
            )

        return attrs


# ============================================================
# Order Item Serializer
# ============================================================


class OrderItemSerializer(serializers.ModelSerializer):
    """
    Shows one item inside an order.
    """

    product_id = serializers.IntegerField(source="product.id", read_only=True)
    seller_id = serializers.IntegerField(source="product.seller_id", read_only=True)
    warehouse_name = serializers.ReadOnlyField(source="warehouse.name")

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product",
            "product_id",
            "seller_id",
            "warehouse",
            "warehouse_name",
            "product_name",
            "product_sku",
            "quantity",
            "unit_price",
            "total_price",
            "created_at",
        ]
        read_only_fields = fields


# ============================================================
# Order Status History Serializer
# ============================================================


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    """
    Shows status changes of an order.
    """

    changed_by_name = serializers.ReadOnlyField(source="changed_by.full_name")

    class Meta:
        model = OrderStatusHistory
        fields = [
            "id",
            "old_status",
            "new_status",
            "changed_by",
            "changed_by_name",
            "note",
            "created_at",
        ]
        read_only_fields = fields


# ============================================================
# Order List Serializer
# ============================================================


class OrderListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for order list.
    """

    items_count = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    payment_status_display = serializers.CharField(
        source="get_payment_status_display",
        read_only=True,
    )

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "status",
            "status_display",
            "payment_status",
            "payment_status_display",
            "items_count",
            "total_amount",
            "created_at",
        ]
        read_only_fields = fields

    def get_items_count(self, obj):
        return obj.items.count()


# ============================================================
# Order Detail Serializer
# ============================================================


class OrderDetailSerializer(serializers.ModelSerializer):
    """
    Full order details with items and status history.
    """

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request is None or not can_view_all(request.user, "orders"):
            fields.pop("admin_note", None)
        return fields


    items = OrderItemSerializer(many=True, read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    payment_status_display = serializers.CharField(
        source="get_payment_status_display",
        read_only=True,
    )

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "user",
            "status",
            "status_display",
            "payment_status",
            "payment_status_display",
            "subtotal",
            "discount_amount",
            "shipping_cost",
            "tax_amount",
            "total_amount",
            "receiver_name",
            "receiver_phone",
            "province",
            "city",
            "address",
            "postal_code",
            "customer_note",
            "admin_note",
            "paid_at",
            "cancelled_at",
            "reservation_expires_at",
            "delivered_at",
            "created_at",
            "updated_at",
            "items",
            "status_history",
        ]
        read_only_fields = fields


# ============================================================
# Seller Order Serializers
# ============================================================


class SellerOrderItemSerializer(serializers.ModelSerializer):
    """
    Item view for sellers.

    Sellers only see order items that belong to their own products.
    """

    product_name = serializers.CharField(read_only=True)
    product_sku = serializers.CharField(read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "quantity",
            "unit_price",
            "total_price",
            "created_at",
        ]
        read_only_fields = fields


class SellerFulfillmentStatusMixin:
    """Expose the current seller's fulfillment independently of Order.status."""

    def _seller_fulfillment(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None

        return obj.seller_fulfillments.filter(
            seller_id=request.user.pk,
        ).first()

    def get_seller_status(self, obj):
        fulfillment = self._seller_fulfillment(obj)
        # Orders created before the new fulfillment model may have no record.
        return fulfillment.status if fulfillment else obj.status

    def get_seller_status_display(self, obj):
        fulfillment = self._seller_fulfillment(obj)
        return (
            fulfillment.get_status_display()
            if fulfillment
            else obj.get_status_display()
        )


class SellerOrderListSerializer(
    SellerFulfillmentStatusMixin,
    serializers.ModelSerializer,
):
    """Order summary with status and totals specific to the current seller."""

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    payment_status_display = serializers.CharField(
        source="get_payment_status_display",
        read_only=True,
    )
    seller_items_count = serializers.SerializerMethodField()
    seller_total_amount = serializers.SerializerMethodField()
    seller_status = serializers.SerializerMethodField()
    seller_status_display = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "status",
            "status_display",
            "payment_status",
            "payment_status_display",
            "seller_items_count",
            "seller_total_amount",
            "seller_status",
            "seller_status_display",
            "created_at",
            "paid_at",
            "delivered_at",
        ]
        read_only_fields = fields

    def _seller_items(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return []

        return [
            item
            for item in obj.items.all()
            if item.product.seller_id == request.user.pk
        ]

    def get_seller_items_count(self, obj):
        return len(self._seller_items(obj))

    def get_seller_total_amount(self, obj):
        return sum(
            (item.total_price for item in self._seller_items(obj)),
            Decimal("0"),
        )


class SellerOrderDetailSerializer(
    SellerFulfillmentStatusMixin,
    serializers.ModelSerializer,
):
    """Order details, exposing only the current seller's order items."""

    items = serializers.SerializerMethodField()
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )
    payment_status_display = serializers.CharField(
        source="get_payment_status_display",
        read_only=True,
    )
    seller_items_count = serializers.SerializerMethodField()
    seller_total_amount = serializers.SerializerMethodField()
    seller_status = serializers.SerializerMethodField()
    seller_status_display = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "status",
            "status_display",
            "payment_status",
            "payment_status_display",
            "seller_items_count",
            "seller_total_amount",
            "seller_status",
            "seller_status_display",
            "receiver_name",
            "receiver_phone",
            "province",
            "city",
            "address",
            "postal_code",
            "customer_note",
            "paid_at",
            "cancelled_at",
            "delivered_at",
            "created_at",
            "updated_at",
            "items",
            "status_history",
        ]
        read_only_fields = fields

    def _seller_items_queryset(self, obj):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return obj.items.none()

        return obj.items.select_related("product").filter(
            product__seller=request.user,
        )

    def get_items(self, obj):
        serializer = SellerOrderItemSerializer(
            self._seller_items_queryset(obj),
            many=True,
        )
        return serializer.data

    def get_seller_items_count(self, obj):
        return self._seller_items_queryset(obj).count()

    def get_seller_total_amount(self, obj):
        return sum(
            (item.total_price for item in self._seller_items_queryset(obj)),
            Decimal("0"),
        )


class SellerOrderStatusUpdateSerializer(serializers.Serializer):
    """Allow sellers to start preparation; Shipping owns dispatch and delivery.

    Sellers may change their paid fulfillment to processing. Shipped and
    delivered must be recorded via the shipment workflow so a seller cannot
    bypass the creation and tracking of their actual shipment.
    """

    status = serializers.ChoiceField(
        choices=[
            (
                Order.StatusChoices.PROCESSING,
                Order.StatusChoices.PROCESSING.label,
            ),
        ],
    )
    note = serializers.CharField(required=False, allow_blank=True)

    def validate_status(self, new_status):
        order = self.context.get("order")
        fulfillment = self.context.get("fulfillment")

        if order is None or fulfillment is None:
            raise serializers.ValidationError("Seller fulfillment is required.")

        if fulfillment.order_id != order.pk:
            raise serializers.ValidationError(
                "Fulfillment does not belong to this order."
            )

        if order.payment_status != Order.PaymentStatusChoices.PAID:
            raise serializers.ValidationError(
                "Only paid orders can be fulfilled by sellers."
            )

        if order.status in {
            Order.StatusChoices.CANCELLED,
            Order.StatusChoices.REFUNDED,
        }:
            raise serializers.ValidationError(
                "This order cannot be changed by the seller."
            )

        if fulfillment.status != Order.StatusChoices.PAID:
            raise serializers.ValidationError(
                "Only paid seller fulfillments can be marked as processing. "
                "Shipping manages subsequent status changes."
            )

        return new_status


# ============================================================
# Checkout Serializer
# ============================================================


class CheckoutSerializer(serializers.Serializer):
    """
    Input serializer for checkout.

    It creates:
    - Order
    - OrderItems
    - Stock reservations

    Input:
    {
        "receiver_name": "Sina",
        "receiver_phone": "09123456789",
        "province": "Tehran",
        "city": "Tehran",
        "address": "Full address",
        "postal_code": "1234567890",
        "customer_note": "optional"
    }
    """

    receiver_name = serializers.CharField(max_length=120)
    receiver_phone = serializers.CharField(max_length=20)
    province = serializers.CharField(max_length=80)
    city = serializers.CharField(max_length=80)
    address = serializers.CharField()
    postal_code = serializers.CharField(max_length=20)
    customer_note = serializers.CharField(required=False, allow_blank=True)

    discount_code = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        write_only=True,
    )
    idempotency_key = serializers.CharField(
        max_length=128, min_length=8, required=False, write_only=True,
    )

    shipping_cost = serializers.DecimalField(
        max_digits=12,
        decimal_places=0,
        required=False,
        min_value=0,
    )

    def validate(self, attrs):
        request = self.context["request"]
        header_key = request.headers.get("Idempotency-Key", "")
        body_key = attrs.get("idempotency_key", "")
        if header_key:
            header_key = serializers.CharField(min_length=8, max_length=128).run_validation(header_key)
        if body_key and header_key and body_key != header_key:
            raise serializers.ValidationError({"idempotency_key": "Header and body keys must match."})
        attrs["idempotency_key"] = header_key or body_key
        attrs["discount_code"] = attrs.get("discount_code", "").strip()
        return attrs

    def create(self, validated_data):
        # Every cart mutation acquires this same Cart lock. Recheck existence,
        # eligibility and totals only after taking it; validation is not a lock.
        user = self.context["request"].user
        values = dict(validated_data)
        key = values.pop("idempotency_key", "")
        fingerprint = hashlib.sha256(
            json.dumps(values, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        with transaction.atomic():
            cart = Cart.objects.select_for_update().filter(user=user).first()
            if key:
                previous = Order.objects.filter(user=user, checkout_key=key).first()
                if previous:
                    if previous.checkout_fingerprint != fingerprint:
                        raise serializers.ValidationError({"idempotency_key": "This key was already used with different checkout details."})
                    return previous
            if cart is None:
                raise serializers.ValidationError("Cart does not exist.")
            items = list(cart.items.select_for_update().order_by("product_id", "pk"))
            if not items:
                raise serializers.ValidationError("Cart is empty.")
            products = {
                product.pk: product
                for product in Product.objects.select_for_update(no_key=True).filter(
                    pk__in=[item.product_id for item in items]
                ).order_by("pk")
            }
            from apps.accounts.models import User
            sellers = {
                seller.pk: seller for seller in User.objects.select_for_update(no_key=True).filter(
                    pk__in={product.seller_id for product in products.values()}
                ).order_by("pk")
            }
            profiles = {
                profile.user_id: profile
                for profile in Seller.objects.select_for_update().filter(
                    user_id__in=sellers
                ).order_by("user_id")
            }
            for item in items:
                product = products.get(item.product_id)
                seller = sellers.get(product.seller_id) if product else None
                profile = profiles.get(product.seller_id) if product else None
                if (
                    product is None or not product.is_active
                    or product.status != Product.StatusChoices.APPROVED
                    or seller is None or not seller.is_active or seller.is_deleted
                    or not seller.is_seller or profile is None
                    or profile.status != Seller.StatusChoices.APPROVED
                ):
                    raise serializers.ValidationError({"product": "A cart product or its seller is no longer eligible for sale."})
                item.product = product
            charge = shipping_charge()
            if "shipping_cost" in values and values["shipping_cost"] != charge:
                raise serializers.ValidationError({"shipping_cost": "Shipping cost must match the server delivery charge."})
            discount_code = values.pop("discount_code", "")
            values.pop("shipping_cost", None)
            try:
                discount = None
                if discount_code:
                    discount, _ = validate_discount_for_cart(code=discount_code, user=user, cart=cart)
                order = Order.objects.create(
                    user=user, subtotal=sum((item.total_price for item in items), Decimal("0")),
                    shipping_cost=charge, checkout_key=key,
                    checkout_fingerprint=fingerprint if key else "",
                    reservation_expires_at=reservation_deadline(), **values,
                )
                for item in items:
                    stock = self._reserve_from_first_available_stock(item.product, item.quantity, user)
                    OrderItem.objects.create(
                        order=order, product=item.product, warehouse=stock.warehouse,
                        product_name=item.product.name, product_sku=item.product.sku,
                        quantity=item.quantity, unit_price=item.unit_price,
                        total_price=item.total_price,
                    )
                    SellerOrderFulfillment.objects.get_or_create(order=order, seller_id=item.product.seller_id)
                if discount is not None:
                    apply_discount_to_order(discount=discount, user=user, cart=cart, order=order)
                    order.refresh_from_db()
                if getattr(settings, "SETTLEMENTS_LEDGER_ENABLED", False):
                    from apps.settlements.services import build_order_allocations
                    build_order_allocations(order, currency="IRR")
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"detail": exc.messages}) from exc
            OrderStatusHistory.objects.create(
                order=order, old_status="", new_status=order.status,
                changed_by=user, note="Order created from cart.",
            )
            create_order_notification(order=order, template_key="order_created", order_id=order.order_number)
            cart.clear()
            return order

    def _reserve_from_first_available_stock(self, product, quantity, user):
        stocks = Stock.objects.select_for_update(of=("self",)).select_related("warehouse").filter(
            product=product, warehouse__is_active=True,
        ).order_by("pk")
        for stock in stocks:
            if stock.available_quantity >= quantity:
                stock.reserve(quantity=quantity, user=user)
                return stock
        raise serializers.ValidationError({"stock": f"Not enough stock for {product.name}."})


# ============================================================
# Order Status Update Serializer
# ============================================================


class OrderStatusUpdateSerializer(serializers.Serializer):
    """
    Admins can start processing an already-paid order.

    Payment, shipping, cancellation and refund statuses
    must be managed by their dedicated workflows.
    """

    status = serializers.ChoiceField(
        choices=[
            (
                Order.StatusChoices.PROCESSING,
                "Processing",
            ),
        ],
    )

    note = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate_status(self, new_status):
        order = self.context.get("order")

        if order is None:
            raise serializers.ValidationError("Order is required.")

        if (
            order.status != Order.StatusChoices.PAID
            or order.payment_status != Order.PaymentStatusChoices.PAID
        ):
            raise serializers.ValidationError(
                "Only paid orders can be marked as processing."
            )

        return new_status
