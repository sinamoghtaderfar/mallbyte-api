from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.discounts.models import Discount, DiscountUsage


class DiscountUsageInline(admin.TabularInline):
    model = DiscountUsage
    extra = 0
    can_delete = False

    fields = [
        "user_link",
        "order_link",
        "code_snapshot",
        "discount_amount",
        "created_at",
    ]

    readonly_fields = [
        "user_link",
        "order_link",
        "code_snapshot",
        "discount_amount",
        "created_at",
    ]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="User")
    def user_link(self, obj):
        if not obj.user_id:
            return "-"

        url = reverse("admin:accounts_user_change", args=[obj.user_id])
        label = getattr(obj.user, "phone", None) or getattr(obj.user, "email", None) or str(obj.user)

        return format_html('<a href="{}">{}</a>', url, label)

    @admin.display(description="Order")
    def order_link(self, obj):
        if not obj.order_id:
            return "-"

        url = reverse("admin:orders_order_change", args=[obj.order_id])
        return format_html('<a href="{}">{}</a>', url, obj.order.order_number)


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "title",
        "discount_type",
        "value",
        "max_discount_amount",
        "min_order_amount",
        "is_active",
        "used_count",
        "usage_limit_total",
        "start_at",
        "end_at",
        "created_at",
    ]

    list_filter = [
        "discount_type",
        "is_active",
        "start_at",
        "end_at",
        "created_at",
    ]

    search_fields = [
        "code",
        "title",
        "description",
    ]

    readonly_fields = [
        "used_count",
        "created_at",
        "updated_at",
    ]

    filter_horizontal = [
        "applicable_products",
        "applicable_categories",
    ]

    list_per_page = 50
    date_hierarchy = "created_at"

    inlines = [
        DiscountUsageInline,
    ]

    fieldsets = (
        (
            "Basic Info",
            {
                "fields": (
                    "code",
                    "title",
                    "description",
                    "is_active",
                )
            },
        ),
        (
            "Discount Rule",
            {
                "fields": (
                    "discount_type",
                    "value",
                    "max_discount_amount",
                    "min_order_amount",
                )
            },
        ),
        (
            "Usage Limits",
            {
                "fields": (
                    "usage_limit_total",
                    "usage_limit_per_user",
                    "used_count",
                )
            },
        ),
        (
            "Schedule",
            {
                "fields": (
                    "start_at",
                    "end_at",
                )
            },
        ),
        (
            "Targeting",
            {
                "fields": (
                    "applicable_products",
                    "applicable_categories",
                )
            },
        ),
        (
            "Meta",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)


@admin.register(DiscountUsage)
class DiscountUsageAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "discount_link",
        "user_link",
        "order_link",
        "code_snapshot",
        "discount_amount",
        "created_at",
    ]

    list_filter = [
        "created_at",
    ]

    search_fields = [
        "code_snapshot",
        "discount__code",
        "user__phone",
        "user__email",
        "order__order_number",
    ]

    readonly_fields = [
        "discount_link",
        "user_link",
        "order_link",
        "code_snapshot",
        "discount_amount",
        "created_at",
    ]

    fields = [
        "discount_link",
        "user_link",
        "order_link",
        "code_snapshot",
        "discount_amount",
        "created_at",
    ]

    list_select_related = [
        "discount",
        "user",
        "order",
    ]

    date_hierarchy = "created_at"
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Discount")
    def discount_link(self, obj):
        if not obj.discount_id:
            return "-"

        url = reverse("admin:discounts_discount_change", args=[obj.discount_id])
        return format_html('<a href="{}">{}</a>', url, obj.discount.code)

    @admin.display(description="User")
    def user_link(self, obj):
        if not obj.user_id:
            return "-"

        url = reverse("admin:accounts_user_change", args=[obj.user_id])
        label = getattr(obj.user, "phone", None) or getattr(obj.user, "email", None) or str(obj.user)

        return format_html('<a href="{}">{}</a>', url, label)

    @admin.display(description="Order")
    def order_link(self, obj):
        if not obj.order_id:
            return "-"

        url = reverse("admin:orders_order_change", args=[obj.order_id])
        return format_html('<a href="{}">{}</a>', url, obj.order.order_number)