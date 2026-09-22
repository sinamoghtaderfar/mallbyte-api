from django.contrib import admin

from .models import WarehouseMembership


@admin.register(WarehouseMembership)
class WarehouseMembershipAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "warehouse",
        "is_active",
        "assigned_by",
        "created_at",
    ]

    list_filter = [
        "warehouse",
        "is_active",
    ]

    search_fields = [
        "user__email",
        "user__full_name",
        "warehouse__name",
        "warehouse__code",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]
