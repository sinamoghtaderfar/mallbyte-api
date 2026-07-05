from django.contrib import admin

from .models import (
    ReturnRequest,
    ReturnItem,
    ReturnAttachment,
    ReturnShipment,
    ReturnStatusHistory,
)


class ReturnItemInline(admin.TabularInline):
    model = ReturnItem
    extra = 0
    readonly_fields = ("created_at", "updated_at")


class ReturnAttachmentInline(admin.TabularInline):
    model = ReturnAttachment
    extra = 0
    readonly_fields = ("created_at", "updated_at")


class ReturnStatusHistoryInline(admin.TabularInline):
    model = ReturnStatusHistory
    extra = 0
    readonly_fields = (
        "old_status",
        "new_status",
        "changed_by",
        "note",
        "created_at",
        "updated_at",
    )
    can_delete = False


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    list_display = (
        "request_number",
        "customer",
        "order",
        "status",
        "reason",
        "requested_resolution",
        "total_requested_amount",
        "total_approved_amount",
        "created_at",
    )

    list_filter = (
        "status",
        "reason",
        "requested_resolution",
        "refund_method",
        "created_at",
    )

    search_fields = (
        "request_number",
        "customer__email",
        "order__id",
        "customer_note",
        "internal_note",
        "customer_note",
        "internal_note",
    )

    readonly_fields = (
        "request_number",
        "created_at",
        "updated_at",
        "reviewed_at",
        "closed_at",
    )

    ordering = ("-created_at",)

    inlines = [
        ReturnItemInline,
        ReturnAttachmentInline,
        ReturnStatusHistoryInline,
    ]


@admin.register(ReturnItem)
class ReturnItemAdmin(admin.ModelAdmin):
    list_display = (
        "return_request",
        "order_item",
        "quantity",
        "reason",
        "condition",
        "status",
        "requested_refund_amount",
        "approved_refund_amount",
        "created_at",
    )

    list_filter = (
        "status",
        "reason",
        "condition",
        "created_at",
    )

    search_fields = (
        "return_request__request_number",
        "order_item__id",
        "customer_note",
        "inspection_note",
    )

    readonly_fields = ("created_at", "updated_at")


@admin.register(ReturnAttachment)
class ReturnAttachmentAdmin(admin.ModelAdmin):
    list_display = (
        "return_request",
        "return_item",
        "attachment_type",
        "uploaded_by",
        "created_at",
    )

    list_filter = (
        "attachment_type",
        "created_at",
    )

    search_fields = (
        "return_request__request_number",
        "caption",
    )

    readonly_fields = ("created_at", "updated_at")


@admin.register(ReturnShipment)
class ReturnShipmentAdmin(admin.ModelAdmin):
    list_display = (
        "return_request",
        "carrier",
        "tracking_number",
        "shipped_at",
        "received_at",
        "created_at",
    )

    search_fields = (
        "return_request__request_number",
        "carrier",
        "tracking_number",
    )

    readonly_fields = ("created_at", "updated_at")


@admin.register(ReturnStatusHistory)
class ReturnStatusHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "return_request",
        "old_status",
        "new_status",
        "changed_by",
        "created_at",
    )

    list_filter = (
        "old_status",
        "new_status",
        "created_at",
    )

    search_fields = (
        "return_request__request_number",
        "note",
    )

    readonly_fields = ("created_at", "updated_at")