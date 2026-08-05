from django.contrib import admin

from .models import AdminLog, Permission, Role, RolePermission, UserRole


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "name",
        "level",
        "is_system_role",
        "created_at",
    ]
    list_filter = [
        "is_system_role",
    ]
    search_fields = [
        "name",
        "description",
    ]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "name",
        "codename",
        "module",
    ]
    list_filter = [
        "module",
    ]
    search_fields = [
        "name",
        "codename",
    ]


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "role",
        "permission",
    ]
    list_filter = [
        "role",
        "permission",
    ]
    search_fields = [
        "role__name",
        "permission__name",
        "permission__codename",
    ]


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "role",
        "assigned_by",
        "assigned_at",
        "expires_at",
        "is_active",
    ]
    list_filter = [
        "role",
        "is_active",
    ]
    search_fields = [
        "user__email",
        "user__full_name",
        "role__name",
    ]


@admin.register(AdminLog)
class AdminLogAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "admin",
        "action",
        "target_user",
        "target_role",
        "ip_address",
        "created_at",
    ]
    list_filter = [
        "action",
        "created_at",
    ]
    search_fields = [
        "admin__email",
        "admin__full_name",
        "target_user__email",
        "target_user__full_name",
        "target_role__name",
    ]
    readonly_fields = [
        "created_at",
    ]