from django.contrib import admin

from apps.support.models import SupportTicket, TicketMessage


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
        "created_at",
        "updated_at",
    )

    list_filter = (
        "status",
        "priority",
        "category",
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
    )

    readonly_fields = (
        "ticket_number",
        "last_message_at",
        "resolved_at",
        "closed_at",
        "created_at",
        "updated_at",
    )

    inlines = [TicketMessageInline]


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