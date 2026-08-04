from django.contrib import admin

from apps.support.models import (
    SupportTag,
    SupportTicket,
    TicketAttachment,
    TicketAuditLog,
    TicketMessage,
)


@admin.register(SupportTag)
class SupportTagAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "slug",
        "color",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
        "created_at",
    )

    search_fields = (
        "name",
        "slug",
    )

    readonly_fields = (
        "slug",
        "created_at",
        "updated_at",
    )


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0
    readonly_fields = (
        "sender",
        "message",
        "is_internal_note",
        "created_at",
        "updated_at",
    )

    can_delete = False


class TicketAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 0
    readonly_fields = (
        "uploaded_by",
        "file",
        "original_filename",
        "content_type",
        "size",
        "created_at",
    )

    can_delete = False


class TicketAuditLogInline(admin.TabularInline):
    model = TicketAuditLog
    extra = 0
    readonly_fields = (
        "actor",
        "action",
        "description",
        "metadata",
        "created_at",
    )

    can_delete = False


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ticket_number",
        "customer",
        "assigned_to",
        "subject",
        "category",
        "priority",
        "status",
        "tag_list",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "status",
        "priority",
        "category",
        "tags",
        "created_at",
        "updated_at",
    )

    search_fields = (
        "ticket_number",
        "subject",
        "customer__phone",
        "customer__email",
        "customer__full_name",
        "assigned_to__phone",
        "assigned_to__email",
        "assigned_to__full_name",
        "tags__name",
    )

    readonly_fields = (
        "ticket_number",
        "last_message_at",
        "resolved_at",
        "closed_at",
        "created_at",
        "updated_at",
    )

    filter_horizontal = ("tags",)

    inlines = [
        TicketMessageInline,
        TicketAttachmentInline,
        TicketAuditLogInline,
    ]

    def tag_list(self, obj):
        return ", ".join(obj.tags.values_list("name", flat=True))

    tag_list.short_description = "Tags"


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ticket",
        "sender",
        "is_internal_note",
        "created_at",
    )

    list_filter = (
        "is_internal_note",
        "created_at",
    )

    search_fields = (
        "ticket__ticket_number",
        "ticket__subject",
        "sender__phone",
        "sender__email",
        "sender__full_name",
        "message",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ticket",
        "uploaded_by",
        "original_filename",
        "content_type",
        "size",
        "created_at",
    )

    list_filter = (
        "content_type",
        "created_at",
    )

    search_fields = (
        "ticket__ticket_number",
        "ticket__subject",
        "uploaded_by__phone",
        "uploaded_by__email",
        "uploaded_by__full_name",
        "original_filename",
    )

    readonly_fields = (
        "original_filename",
        "size",
        "created_at",
    )


@admin.register(TicketAuditLog)
class TicketAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ticket",
        "actor",
        "action",
        "created_at",
    )

    list_filter = (
        "action",
        "created_at",
    )

    search_fields = (
        "ticket__ticket_number",
        "ticket__subject",
        "actor__phone",
        "actor__email",
        "actor__full_name",
        "description",
    )

    readonly_fields = (
        "ticket",
        "actor",
        "action",
        "description",
        "metadata",
        "created_at",
    )