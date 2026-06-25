# apps/shipping/admin.py

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html

from apps.shipping.models import Shipment, ShipmentEvent


# ============================================================
# Shared Helpers
# ============================================================

STATUS_COLOR_MAP = {
    Shipment.StatusChoices.PENDING: "#6c757d",
    Shipment.StatusChoices.READY_TO_SHIP: "#0d6efd",
    Shipment.StatusChoices.SHIPPED: "#6610f2",
    Shipment.StatusChoices.IN_TRANSIT: "#fd7e14",
    Shipment.StatusChoices.OUT_FOR_DELIVERY: "#20c997",
    Shipment.StatusChoices.DELIVERED: "#198754",
    Shipment.StatusChoices.FAILED: "#dc3545",
    Shipment.StatusChoices.RETURNED: "#ffc107",
    Shipment.StatusChoices.CANCELLED: "#343a40",
}


def status_badge_html(status, label=None):
    """
    Render a colored status badge for Django admin list pages.
    """

    if not status:
        return "-"

    color = STATUS_COLOR_MAP.get(status, "#6c757d")
    text = label or status

    return format_html(
        '<span style="background:{}; color:white; padding:4px 8px; '
        'border-radius:12px; font-size:12px; font-weight:600;">{}</span>',
        color,
        text,
    )


def safe_admin_link(admin_url_name, object_id, label):
    """
    Create a safe admin link.

    If the target admin model is not registered, this returns plain text
    instead of raising NoReverseMatch.
    """

    if not object_id:
        return "-"

    try:
        url = reverse(admin_url_name, args=[object_id])
    except NoReverseMatch:
        return label or "-"

    return format_html('<a href="{}">{}</a>', url, label)


def user_label(user):
    """
    Best display label for custom User model.
    """

    if not user:
        return "-"

    return (
        getattr(user, "phone", None)
        or getattr(user, "email", None)
        or getattr(user, "full_name", None)
        or str(user)
    )


# ============================================================
# Custom Filters
# ============================================================

class HasTrackingNumberFilter(admin.SimpleListFilter):
    title = "Tracking Number"
    parameter_name = "has_tracking"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Has tracking number"),
            ("no", "No tracking number"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(tracking_number="")

        if self.value() == "no":
            return queryset.filter(tracking_number="")

        return queryset


class ShipmentLifecycleFilter(admin.SimpleListFilter):
    title = "Lifecycle"
    parameter_name = "lifecycle"

    def lookups(self, request, model_admin):
        return (
            ("active", "Active"),
            ("completed", "Completed"),
            ("problem", "Problem"),
        )

    def queryset(self, request, queryset):
        if self.value() == "active":
            return queryset.filter(
                status__in=[
                    Shipment.StatusChoices.PENDING,
                    Shipment.StatusChoices.READY_TO_SHIP,
                    Shipment.StatusChoices.SHIPPED,
                    Shipment.StatusChoices.IN_TRANSIT,
                    Shipment.StatusChoices.OUT_FOR_DELIVERY,
                ]
            )

        if self.value() == "completed":
            return queryset.filter(
                status__in=[
                    Shipment.StatusChoices.DELIVERED,
                    Shipment.StatusChoices.RETURNED,
                    Shipment.StatusChoices.CANCELLED,
                ]
            )

        if self.value() == "problem":
            return queryset.filter(
                status__in=[
                    Shipment.StatusChoices.FAILED,
                    Shipment.StatusChoices.RETURNED,
                    Shipment.StatusChoices.CANCELLED,
                ]
            )

        return queryset


# ============================================================
# Shipment Event Inline
# ============================================================

class ShipmentEventInline(admin.TabularInline):
    """
    Shipment status history shown inside the Shipment admin page.

    This is an audit log, so it must stay read-only.
    """

    model = ShipmentEvent
    extra = 0
    can_delete = False
    show_change_link = True

    fields = [
        "old_status_badge",
        "new_status_badge",
        "message",
        "created_by_link",
        "created_at",
    ]

    readonly_fields = [
        "old_status_badge",
        "new_status_badge",
        "message",
        "created_by_link",
        "created_at",
    ]

    ordering = [
        "created_at",
        "id",
    ]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("created_by")
            .order_by("created_at", "id")
        )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Old Status", ordering="old_status")
    def old_status_badge(self, obj):
        return status_badge_html(obj.old_status)

    @admin.display(description="New Status", ordering="new_status")
    def new_status_badge(self, obj):
        return status_badge_html(obj.new_status)

    @admin.display(description="Created By")
    def created_by_link(self, obj):
        if not obj.created_by_id:
            return "-"

        return safe_admin_link(
            admin_url_name="admin:accounts_user_change",
            object_id=obj.created_by_id,
            label=user_label(obj.created_by),
        )


# ============================================================
# Shipment Admin
# ============================================================

@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    """
    Professional admin page for managing shipments.

    Important:
    Shipment status should not be edited directly because shipment
    methods also update order status and create audit logs.
    """

    FINAL_STATUSES = [
        Shipment.StatusChoices.DELIVERED,
        Shipment.StatusChoices.CANCELLED,
        Shipment.StatusChoices.RETURNED,
    ]

    list_display = [
        "shipment_number",
        "order_link",
        "customer_link",
        "status_badge",
        "carrier",
        "tracking_display",
        "city",
        "shipping_cost",
        "shipped_at",
        "delivered_at",
        "created_at",
    ]

    list_filter = [
        "status",
        "carrier",
        HasTrackingNumberFilter,
        ShipmentLifecycleFilter,
        "province",
        "city",
        "created_at",
        "shipped_at",
        "delivered_at",
        "cancelled_at",
    ]

    search_fields = [
        "shipment_number",
        "tracking_number",
        "order__order_number",
        "user__phone",
        "user__email",
        "user__full_name",
        "receiver_name",
        "receiver_phone",
        "province",
        "city",
        "postal_code",
    ]

    readonly_fields = [
        "shipment_number",
        "order_admin_link",
        "user_admin_link",
        "status",
        "created_by_admin_link",
        "shipped_at",
        "delivered_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    ]

    list_select_related = [
        "order",
        "user",
        "created_by",
    ]

    date_hierarchy = "created_at"
    list_per_page = 50
    save_on_top = True

    ordering = [
        "-created_at",
        "-id",
    ]

    inlines = [
        ShipmentEventInline,
    ]

    actions = [
        "mark_selected_as_ready",
        "mark_selected_as_shipped",
        "mark_selected_as_delivered",
        "cancel_selected_shipments",
    ]

    fieldsets = (
        (
            "Shipment Info",
            {
                "fields": (
                    "shipment_number",
                    "order_admin_link",
                    "user_admin_link",
                    "carrier",
                    "status",
                    "shipping_cost",
                    "created_by_admin_link",
                )
            },
        ),
        (
            "Tracking",
            {
                "fields": (
                    "tracking_number",
                    "tracking_url",
                )
            },
        ),
        (
            "Receiver Address",
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
                    "notes",
                )
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "shipped_at",
                    "delivered_at",
                    "cancelled_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("order", "user", "created_by")
        )

    def has_add_permission(self, request):
        """
        Shipments should be created from paid orders,
        not manually from the admin panel.
        """
        return False

    def is_final_status(self, obj):
        return obj is not None and obj.status in self.FINAL_STATUSES

    def has_view_permission(self, request, obj=None):
        return True

    def has_change_permission(self, request, obj=None):
        """
        Final shipments are audit-sensitive records.
        They can be viewed, but not changed from admin.
        """
        if self.is_final_status(obj):
            return False

        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """
        Do not allow deleting shipments from admin because shipment
        records are operational/audit records.
        """
        return False

    # ------------------------------------------------------------
    # Admin display helpers
    # ------------------------------------------------------------

    @admin.display(description="Order", ordering="order__order_number")
    def order_link(self, obj):
        return self.order_admin_link(obj)

    @admin.display(description="Customer", ordering="user__phone")
    def customer_link(self, obj):
        return self.user_admin_link(obj)

    @admin.display(description="Order")
    def order_admin_link(self, obj):
        if not obj.order_id:
            return "-"

        return safe_admin_link(
            admin_url_name="admin:orders_order_change",
            object_id=obj.order_id,
            label=obj.order.order_number,
        )

    @admin.display(description="Customer")
    def user_admin_link(self, obj):
        if not obj.user_id:
            return "-"

        return safe_admin_link(
            admin_url_name="admin:accounts_user_change",
            object_id=obj.user_id,
            label=user_label(obj.user),
        )

    @admin.display(description="Created By")
    def created_by_admin_link(self, obj):
        if not obj.created_by_id:
            return "-"

        return safe_admin_link(
            admin_url_name="admin:accounts_user_change",
            object_id=obj.created_by_id,
            label=user_label(obj.created_by),
        )

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return status_badge_html(
            status=obj.status,
            label=obj.get_status_display(),
        )

    @admin.display(description="Tracking", ordering="tracking_number")
    def tracking_display(self, obj):
        if not obj.tracking_number:
            return "-"

        if obj.tracking_url:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
                obj.tracking_url,
                obj.tracking_number,
            )

        return obj.tracking_number

    # ------------------------------------------------------------
    # Admin actions
    # ------------------------------------------------------------

    def _run_shipment_action(self, request, queryset, action_func, success_message):
        success_count = 0
        errors = []

        for shipment in queryset.select_related("order", "user"):
            try:
                action_func(shipment)
                success_count += 1

            except ValidationError as exc:
                message = exc.messages[0] if hasattr(exc, "messages") else str(exc)
                errors.append(f"{shipment.shipment_number}: {message}")

            except Exception as exc:
                errors.append(f"{shipment.shipment_number}: {str(exc)}")

        if success_count:
            self.message_user(
                request,
                f"{success_count} shipment(s) {success_message}.",
                level=messages.SUCCESS,
            )

        for error in errors[:5]:
            self.message_user(
                request,
                error,
                level=messages.ERROR,
            )

        if len(errors) > 5:
            self.message_user(
                request,
                f"{len(errors) - 5} more error(s) hidden.",
                level=messages.WARNING,
            )

    @admin.action(description="Mark selected shipments as ready to ship")
    def mark_selected_as_ready(self, request, queryset):
        self._run_shipment_action(
            request=request,
            queryset=queryset,
            action_func=lambda shipment: shipment.mark_ready(
                user=request.user,
                note="Marked as ready from Django admin.",
            ),
            success_message="marked as ready to ship",
        )

    @admin.action(description="Mark selected shipments as shipped")
    def mark_selected_as_shipped(self, request, queryset):
        def action(shipment):
            if not shipment.tracking_number:
                raise ValidationError(
                    "Tracking number is required before marking shipment as shipped."
                )

            shipment.mark_shipped(
                tracking_number=shipment.tracking_number,
                tracking_url=shipment.tracking_url,
                user=request.user,
                note="Marked as shipped from Django admin.",
            )

        self._run_shipment_action(
            request=request,
            queryset=queryset,
            action_func=action,
            success_message="marked as shipped",
        )

    @admin.action(description="Mark selected shipments as delivered")
    def mark_selected_as_delivered(self, request, queryset):
        self._run_shipment_action(
            request=request,
            queryset=queryset,
            action_func=lambda shipment: shipment.mark_delivered(
                user=request.user,
                note="Marked as delivered from Django admin.",
            ),
            success_message="marked as delivered",
        )

    @admin.action(description="Cancel selected shipments")
    def cancel_selected_shipments(self, request, queryset):
        self._run_shipment_action(
            request=request,
            queryset=queryset,
            action_func=lambda shipment: shipment.cancel(
                user=request.user,
                note="Cancelled from Django admin.",
            ),
            success_message="cancelled",
        )


# ============================================================
# Shipment Event Admin
# ============================================================

@admin.register(ShipmentEvent)
class ShipmentEventAdmin(admin.ModelAdmin):
    """
    Admin page for shipment event logs.

    Shipment events are audit logs. They should be searchable
    and inspectable, but not manually created, changed, or deleted.
    """

    list_display = [
        "id",
        "shipment_link",
        "old_status_badge",
        "new_status_badge",
        "created_by_link",
        "created_at",
    ]

    list_filter = [
        "old_status",
        "new_status",
        "created_at",
    ]

    search_fields = [
        "shipment__shipment_number",
        "shipment__tracking_number",
        "shipment__order__order_number",
        "message",
        "created_by__phone",
        "created_by__email",
    ]

    readonly_fields = [
        "shipment_link",
        "old_status_badge",
        "new_status_badge",
        "message",
        "data",
        "created_by_link",
        "created_at",
    ]

    fields = [
        "shipment_link",
        "old_status_badge",
        "new_status_badge",
        "message",
        "data",
        "created_by_link",
        "created_at",
    ]

    list_select_related = [
        "shipment",
        "created_by",
    ]

    date_hierarchy = "created_at"
    list_per_page = 50

    ordering = [
        "created_at",
        "id",
    ]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("shipment", "created_by")
            .order_by("created_at", "id")
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Shipment", ordering="shipment__shipment_number")
    def shipment_link(self, obj):
        if not obj.shipment_id:
            return "-"

        return safe_admin_link(
            admin_url_name="admin:shipping_shipment_change",
            object_id=obj.shipment_id,
            label=obj.shipment.shipment_number,
        )

    @admin.display(description="Created By")
    def created_by_link(self, obj):
        if not obj.created_by_id:
            return "-"

        return safe_admin_link(
            admin_url_name="admin:accounts_user_change",
            object_id=obj.created_by_id,
            label=user_label(obj.created_by),
        )

    @admin.display(description="Old Status", ordering="old_status")
    def old_status_badge(self, obj):
        return status_badge_html(obj.old_status)

    @admin.display(description="New Status", ordering="new_status")
    def new_status_badge(self, obj):
        return status_badge_html(obj.new_status)