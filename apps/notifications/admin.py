from django.contrib import admin

from apps.notifications.models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "title",
        "notification_type",
        "channel",
        "priority",
        "is_read",
        "created_at",
    )

    list_filter = (
        "notification_type",
        "channel",
        "priority",
        "is_read",
        "created_at",
    )

    search_fields = (
        "title",
        "message",
        "user__phone",
        "user__email",
        "user__full_name",
        "related_object_type",
        "related_object_id",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "read_at",
    )

    ordering = ("-created_at",)

    actions = [
        "mark_selected_as_read",
        "mark_selected_as_unread",
    ]

    @admin.action(description="Mark selected notifications as read")
    def mark_selected_as_read(self, request, queryset):
        for notification in queryset:
            notification.mark_as_read()

    @admin.action(description="Mark selected notifications as unread")
    def mark_selected_as_unread(self, request, queryset):
        for notification in queryset:
            notification.mark_as_unread()


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "email_enabled",
        "sms_enabled",
        "push_enabled",
        "in_app_enabled",
        "created_at",
    )
    search_fields = (
        "user__phone",
        "user__email",
        "user__full_name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
