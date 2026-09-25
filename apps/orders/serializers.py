from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from apps.discounts.services import apply_discount_to_order, validate_discount_for_cart
from apps.inventory.models import Stock
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
    warehouse_name = serializers.ReadOnlyField(source="warehouse.name")

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "product",
            "product_id",
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
    """Validate a transition of the seller's own fulfillment, not the order."""

    status = serializers.ChoiceField(
        choices=[
            (
                Order.StatusChoices.PROCESSING,
                Order.StatusChoices.PROCESSING.label,
            ),
            (
                Order.StatusChoices.SHIPPED,
                Order.StatusChoices.SHIPPED.label,
            ),
            (
                Order.StatusChoices.DELIVERED,
                Order.StatusChoices.DELIVERED.label,
            ),
        ],
    )
    note = serializers.CharField(required=False, allow_blank=True)

    allowed_transitions = {
        Order.StatusChoices.PAID: {Order.StatusChoices.PROCESSING},
        Order.StatusChoices.PROCESSING: {Order.StatusChoices.SHIPPED},
        Order.StatusChoices.SHIPPED: {Order.StatusChoices.DELIVERED},
    }

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

        allowed = self.allowed_transitions.get(fulfillment.status, set())
        if new_status not in allowed:
            raise serializers.ValidationError(
                "Invalid seller fulfillment status transition."
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

    shipping_cost = serializers.DecimalField(
        max_digits=12,
        decimal_places=0,
        required=False,
        default=0,
        min_value=0,
    )

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user

        try:
            cart = user.cart
        except Cart.DoesNotExist as exc:
            raise serializers.ValidationError("Cart does not exist.") from exc

        if not cart.items.exists():
            raise serializers.ValidationError("Cart is empty.")

        # Check stock for each cart item before checkout.
        for item in cart.items.select_related("product"):
            if item.product.available_stock < item.quantity:
                raise serializers.ValidationError(
                    {"stock": f"Not enough stock for {item.product.name}."}
                )

        discount_code = attrs.get("discount_code", "").strip()

        if discount_code:
            try:
                discount, discount_amount = validate_discount_for_cart(
                    code=discount_code,
                    user=user,
                    cart=cart,
                )
            except DjangoValidationError as exc:
                message = exc.messages[0] if hasattr(exc, "messages") else str(exc)

                raise serializers.ValidationError(
                    {
                        "discount_code": message,
                    }
                ) from exc

            attrs["discount"] = discount
            attrs["discount_amount"] = discount_amount
        else:
            attrs["discount"] = None
            attrs["discount_amount"] = 0

        attrs["cart"] = cart
        return attrs

    def create(self, validated_data):
        """
        Create order from cart.

        Important:
        - We reserve stock here.
        - Discount is applied before payment.
        - Payment will be handled later in payments app.
        """
        request = self.context["request"]
        user = request.user
        cart = validated_data.pop("cart")

        discount = validated_data.pop("discount", None)
        validated_data.pop("discount_amount", 0)
        validated_data.pop("discount_code", "")

        shipping_cost = validated_data.pop("shipping_cost", 0)

        with transaction.atomic():
            order = Order.objects.create(
                user=user,
                subtotal=cart.subtotal,
                discount_amount=0,
                shipping_cost=shipping_cost,
                receiver_name=validated_data["receiver_name"],
                receiver_phone=validated_data["receiver_phone"],
                province=validated_data["province"],
                city=validated_data["city"],
                address=validated_data["address"],
                postal_code=validated_data["postal_code"],
                customer_note=validated_data.get("customer_note", ""),
            )

            for cart_item in cart.items.select_related("product"):
                stock = self._reserve_from_first_available_stock(
                    product=cart_item.product,
                    quantity=cart_item.quantity,
                    user=user,
                )

                OrderItem.objects.create(
                    order=order,
                    product=cart_item.product,
                    warehouse=stock.warehouse,
                    product_name=cart_item.product.name,
                    product_sku=cart_item.product.sku,
                    quantity=cart_item.quantity,
                    unit_price=cart_item.unit_price,
                    total_price=cart_item.total_price,
                )
                SellerOrderFulfillment.objects.get_or_create(
                    order=order,
                    seller=cart_item.product.seller,
                    defaults={
                        "status": Order.StatusChoices.PENDING_PAYMENT,
                    },
                )
            if discount is not None:
                apply_discount_to_order(
                    discount=discount,
                    user=user,
                    cart=cart,
                    order=order,
                )
                order.refresh_from_db()

            OrderStatusHistory.objects.create(
                order=order,
                old_status="",
                new_status=order.status,
                changed_by=user,
                note="Order created from cart.",
            )
            create_order_notification(
                order=order,
                template_key="order_created",
                order_id=order.order_number,
            )
            cart.clear()

        return order

    def _reserve_from_first_available_stock(self, product, quantity, user):
        """
        Reserve stock from the first warehouse that has enough available stock.

        Later we can improve this with:
        - nearest warehouse
        - seller warehouse
        - shipping zone
        """

        stocks = (
            Stock.objects.select_related("warehouse")
            .filter(product=product, warehouse__is_active=True)
            .order_by("id")
        )

        for stock in stocks:
            if stock.available_quantity >= quantity:
                stock.reserve(quantity=quantity, user=user)
                stock.refresh_from_db()
                return stock

        raise serializers.ValidationError(
            {"stock": f"Not enough stock for {product.name}."}
        )


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
