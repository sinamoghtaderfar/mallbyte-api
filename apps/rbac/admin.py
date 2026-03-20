from django.contrib import admin
from .models import Role, Permission, RolePermission, UserRole

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    
    list_display = ['id', 'name', 'level', 'is_system_role', 'created_at']
    list_filter = ['is_system_role']
    search_fields = ['name', 'description']
    
@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    
    list_display = ['id', 'name', 'codename', 'module']
    list_filter = ['module']
    search_fields = ['name', 'codename']
    

@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ['id', 'role', 'permission']
    list_filter = ['role', 'permission']


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'role', 'assigned_by', 'assigned_at', 'expires_at', 'is_active']
    list_filter = ['role', 'is_active']
    search_fields = ['user__phone', 'user__email']