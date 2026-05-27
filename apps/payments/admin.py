# apps/payments/admin.py

from django.contrib import admin

from apps.payments.models import Payment, PaymentEvent


# ============================================================
# Payment Events inside Payment page
# ============================================================

class PaymentEventInline(admin.TabularInline):
    """
    Show payment logs inside each Payment page.
    Example:
    pending -> success
    pending -> failed
    """

    model = PaymentEvent
    extra = 0
    can_delete = False

    fields = [
        "event_type",
        "old_status",
        "new_status",
        "message",
        "created_at",
    ]

    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


# ============================================================
# Payment Admin
# ============================================================

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    Admin page for payments.

    We use this page only to view payments.
    Payment should be created by API, not manually from admin.
    """

    list_display = [
        "payment_number",
        "order",
        "user",
        "provider",
        "status",
        "amount",
        "currency",
        "created_at",
        "paid_at",
    ]

    list_filter = [
        "provider",
        "status",
        "created_at",
        "paid_at",
    ]

    search_fields = [
        "payment_number",
        "order__order_number",
        "user__phone",
        "user__email",
        "gateway_reference",
    ]

    readonly_fields = [
        "payment_number",
        "order",
        "user",
        "provider",
        "status",
        "amount",
        "currency",
        "gateway_reference",
        "gateway_response",
        "failure_reason",
        "paid_at",
        "failed_at",
        "cancelled_at",
        "refunded_at",
        "created_by",
        "created_at",
        "updated_at",
    ]

    inlines = [
        PaymentEventInline,
    ]

    def has_add_permission(self, request):
        """
        Do not create payments manually from admin.
        Payments must be created by API.
        """
        return False

    def has_delete_permission(self, request, obj=None):
        """
        Do not delete payment records.
        Payments are financial records.
        """
        return False


# ============================================================
# Payment Event Admin
# ============================================================

@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    """
    Admin page for payment logs/events.
    """

    list_display = [
        "id",
        "payment",
        "event_type",
        "old_status",
        "new_status",
        "created_at",
    ]

    list_filter = [
        "event_type",
        "old_status",
        "new_status",
        "created_at",
    ]

    search_fields = [
        "payment__payment_number",
        "payment__order__order_number",
        "message",
    ]

    readonly_fields = [
        "payment",
        "event_type",
        "old_status",
        "new_status",
        "message",
        "data",
        "created_by",
        "created_at",
    ]

    def has_add_permission(self, request):
        """
        Events are logs.
        They must be created by system logic.
        """
        return False

    def has_delete_permission(self, request, obj=None):
        """
        Do not delete payment logs.
        """
        return False