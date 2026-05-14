# apps/orders/admin.py

from django.contrib import admin

from apps.orders.models import (
    Cart,
    CartItem,
    Order,
    OrderItem,
    OrderStatusHistory,
)


# ============================================================
# Cart Admin
# ============================================================

class CartItemInline(admin.TabularInline):
    """
    Show cart items inside Cart admin page.
    """

    model = CartItem
    extra = 0
    readonly_fields = [
        "product",
        "quantity",
        "unit_price",
        "total_price",
        "created_at",
        "updated_at",
    ]

    fields = [
        "product",
        "quantity",
        "unit_price",
        "total_price",
        "created_at",
        "updated_at",
    ]

    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    """
    Admin page for user carts.
    """

    list_display = [
        "id",
        "user_phone",
        "user_full_name",
        "total_items",
        "subtotal",
        "created_at",
        "updated_at",
    ]

    search_fields = [
        "user__phone",
        "user__email",
        "user__full_name",
    ]

    readonly_fields = [
        "user",
        "total_items",
        "subtotal",
        "created_at",
        "updated_at",
    ]

    list_select_related = ["user"]
    inlines = [CartItemInline]

    def user_phone(self, obj):
        return obj.user.phone

    user_phone.short_description = "Phone"

    def user_full_name(self, obj):
        return obj.user.full_name

    user_full_name.short_description = "Full Name"


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    """
    Admin page for cart items.
    Mostly for debugging.
    """

    list_display = [
        "id",
        "cart",
        "product",
        "quantity",
        "unit_price",
        "total_price",
        "created_at",
    ]

    search_fields = [
        "cart__user__phone",
        "product__name",
        "product__sku",
    ]

    list_filter = [
        "created_at",
    ]

    readonly_fields = [
        "total_price",
        "created_at",
        "updated_at",
    ]

    list_select_related = [
        "cart",
        "cart__user",
        "product",
    ]


# ============================================================
# Order Admin
# ============================================================

class OrderItemInline(admin.TabularInline):
    """
    Show order items inside Order admin page.

    Order items are snapshots, so we keep them read-only.
    """

    model = OrderItem
    extra = 0
    can_delete = False

    fields = [
        "product",
        "warehouse",
        "product_name",
        "product_sku",
        "quantity",
        "unit_price",
        "total_price",
        "created_at",
    ]

    readonly_fields = [
        "product",
        "warehouse",
        "product_name",
        "product_sku",
        "quantity",
        "unit_price",
        "total_price",
        "created_at",
    ]

    def has_add_permission(self, request, obj=None):
        return False


class OrderStatusHistoryInline(admin.TabularInline):
    """
    Show order status changes inside Order admin page.
    """

    model = OrderStatusHistory
    extra = 0
    can_delete = False

    fields = [
        "old_status",
        "new_status",
        "changed_by",
        "note",
        "created_at",
    ]

    readonly_fields = [
        "old_status",
        "new_status",
        "changed_by",
        "note",
        "created_at",
    ]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """
    Admin page for orders.

    Admin can inspect orders, items, customer info,
    payment status, and status history.
    """

    list_display = [
        "order_number",
        "user_phone",
        "status",
        "payment_status",
        "total_amount",
        "items_count",
        "created_at",
    ]

    list_filter = [
        "status",
        "payment_status",
        "created_at",
        "paid_at",
        "cancelled_at",
    ]

    search_fields = [
        "order_number",
        "user__phone",
        "user__email",
        "user__full_name",
        "receiver_name",
        "receiver_phone",
        "postal_code",
    ]

    readonly_fields = [
        "order_number",
        "user",
        "subtotal",
        "discount_amount",
        "shipping_cost",
        "tax_amount",
        "total_amount",
        "paid_at",
        "cancelled_at",
        "delivered_at",
        "created_at",
        "updated_at",
    ]

    list_select_related = ["user"]
    date_hierarchy = "created_at"

    inlines = [
        OrderItemInline,
        OrderStatusHistoryInline,
    ]

    fieldsets = (
        (
            "Order Info",
            {
                "fields": (
                    "order_number",
                    "user",
                    "status",
                    "payment_status",
                )
            },
        ),
        (
            "Amounts",
            {
                "fields": (
                    "subtotal",
                    "discount_amount",
                    "shipping_cost",
                    "tax_amount",
                    "total_amount",
                )
            },
        ),
        (
            "Shipping Address",
            {
                "fields": (
                    "receiver_name",
                    "receiver_phone",
                    "province",
                    "city",
                    "address",
                    "postal_code",
                )
            },
        ),
        (
            "Notes",
            {
                "fields": (
                    "customer_note",
                    "admin_note",
                )
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "paid_at",
                    "cancelled_at",
                    "delivered_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def user_phone(self, obj):
        return obj.user.phone

    user_phone.short_description = "Customer Phone"

    def items_count(self, obj):
        return obj.items.count()

    items_count.short_description = "Items"


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    """
    Admin page for order items.
    Useful for searching product sales.
    """

    list_display = [
        "id",
        "order",
        "product_name",
        "product_sku",
        "warehouse",
        "quantity",
        "unit_price",
        "total_price",
        "created_at",
    ]

    search_fields = [
        "order__order_number",
        "product_name",
        "product_sku",
        "product__name",
        "product__sku",
    ]

    list_filter = [
        "warehouse",
        "created_at",
    ]

    readonly_fields = [
        "order",
        "product",
        "warehouse",
        "product_name",
        "product_sku",
        "quantity",
        "unit_price",
        "total_price",
        "created_at",
    ]

    list_select_related = [
        "order",
        "product",
        "warehouse",
    ]


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    """
    Admin page for order status history.
    """

    list_display = [
        "id",
        "order",
        "old_status",
        "new_status",
        "changed_by",
        "created_at",
    ]

    search_fields = [
        "order__order_number",
        "changed_by__phone",
        "changed_by__email",
        "note",
    ]

    list_filter = [
        "old_status",
        "new_status",
        "created_at",
    ]

    readonly_fields = [
        "order",
        "old_status",
        "new_status",
        "changed_by",
        "note",
        "created_at",
    ]

    list_select_related = [
        "order",
        "changed_by",
    ]