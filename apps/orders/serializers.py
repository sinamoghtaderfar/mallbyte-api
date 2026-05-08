from django.db import transaction
from rest_framework import serializers

from apps.inventory.models import Stock
from apps.orders.models import Cart, CartItem, Order, OrderItem, OrderStatusHistory
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
                {
                    "quantity": "Not enough available stock."
                }
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
                {
                    "quantity": "Not enough available stock."
                }
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
        except Cart.DoesNotExist:
            raise serializers.ValidationError("Cart does not exist.")

        if not cart.items.exists():
            raise serializers.ValidationError("Cart is empty.")

        # Check stock for each cart item before checkout.
        for item in cart.items.select_related("product"):
            if item.product.available_stock < item.quantity:
                raise serializers.ValidationError(
                    {
                        "stock": f"Not enough stock for {item.product.name}."
                    }
                )

        attrs["cart"] = cart
        return attrs

    def create(self, validated_data):
        """
        Create order from cart.

        Important:
        - We reserve stock here.
        - Payment will be handled later in payments app.
        """
        request = self.context["request"]
        user = request.user
        cart = validated_data.pop("cart")

        shipping_cost = validated_data.pop("shipping_cost", 0)

        with transaction.atomic():
            order = Order.objects.create(
                user=user,
                subtotal=cart.subtotal,
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

            OrderStatusHistory.objects.create(
                order=order,
                old_status="",
                new_status=order.status,
                changed_by=user,
                note="Order created from cart.",
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
            Stock.objects
            .select_related("warehouse")
            .filter(product=product, warehouse__is_active=True)
            .order_by("id")
        )

        for stock in stocks:
            if stock.available_quantity >= quantity:
                stock.reserve(quantity=quantity, user=user)
                stock.refresh_from_db()
                return stock

        raise serializers.ValidationError(
            {
                "stock": f"Not enough stock for {product.name}."
            }
        )


# ============================================================
# Order Status Update Serializer
# ============================================================

class OrderStatusUpdateSerializer(serializers.Serializer):
    """
    Admin serializer for changing order status.

    Input:
    {
        "status": "processing",
        "note": "Order is being prepared"
    }
    """

    status = serializers.ChoiceField(choices=Order.StatusChoices.choices)
    note = serializers.CharField(required=False, allow_blank=True)

    def validate_status(self, new_status):
        order = self.context.get("order")

        if not order:
            return new_status

        if order.status == Order.StatusChoices.CANCELLED:
            raise serializers.ValidationError("Cancelled orders cannot be changed.")

        if order.status == Order.StatusChoices.DELIVERED:
            raise serializers.ValidationError("Delivered orders cannot be changed.")

        if order.status == new_status:
            raise serializers.ValidationError("Order already has this status.")

        return new_status