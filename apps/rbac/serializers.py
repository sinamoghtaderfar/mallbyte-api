from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Role, Permission, RolePermission, UserRole, AdminLog

User = get_user_model()

class RoleSerializer(serializers.ModelSerializer):
    """Serializer for Role model"""
    permissions = serializers.SerializerMethodField()
    permissions_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Role
        fields = ['id', 'name', 'description', 'level', 'is_system_role', 
                  'permissions', 'permissions_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at', 'is_system_role']
        
    def get_permissions(self, obj):
        return [rp.permission.codename for rp in obj.role_permissions.all()]

    def get_permissions_count(self, obj):
        return obj.role_permissions.count()

class PermissionSerializer(serializers.ModelSerializer):
    """Serializer for Permission model"""

    class Meta:
        model = Permission
        fields = ['id', 'name', 'codename', 'module', 'description', 'created_at']
        read_only_fields = ['id', 'created_at']
class RolePermissionSerializer(serializers.ModelSerializer):
    """Serializer for Role-Permission assignments"""
    role_name = serializers.ReadOnlyField(source='role.name')
    permission_name = serializers.ReadOnlyField(source='permission.name')
    permission_codename = serializers.ReadOnlyField(source='permission.codename')

    class Meta:
        model = RolePermission
        fields = ['id', 'role', 'role_name', 'permission', 'permission_name', 'permission_codename']


class UserRoleSerializer(serializers.ModelSerializer):
    """Serializer for User-Role assignments"""
    role_name = serializers.ReadOnlyField(source='role.name')
    role_level = serializers.ReadOnlyField(source='role.level')
    assigned_by_name = serializers.SerializerMethodField()
    user_phone = serializers.ReadOnlyField(source='user.phone')

    class Meta:
        model = UserRole
        fields = ['id', 'user', 'user_phone', 'role', 'role_name', 'role_level',
                  'assigned_by', 'assigned_by_name', 'assigned_at', 'expires_at', 'is_active']
        read_only_fields = ['id', 'assigned_at']

    def get_assigned_by_name(self, obj):
        if obj.assigned_by:
            return obj.assigned_by.full_name or obj.assigned_by.phone
        return None


class AssignRoleSerializer(serializers.Serializer):
    """Serializer for assigning role to user"""
    user_id = serializers.IntegerField()
    role_id = serializers.IntegerField()
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_user_id(self, value):
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("User does not exist")
        return value

    def validate_role_id(self, value):
        if not Role.objects.filter(id=value).exists():
            raise serializers.ValidationError("Role does not exist")
        return value


class CheckPermissionSerializer(serializers.Serializer):
    """Serializer for checking user permission"""
    user_id = serializers.IntegerField()
    permission = serializers.CharField()


class UserPermissionsSerializer(serializers.Serializer):
    """Serializer for user permissions"""
    user_id = serializers.IntegerField()
    permissions = serializers.ListField(child=serializers.CharField())
    


class AdminLogSerializer(serializers.ModelSerializer):
    """Serializer for admin action logs"""
    admin_name = serializers.SerializerMethodField()
    admin_phone = serializers.SerializerMethodField()
    target_user_name = serializers.SerializerMethodField()
    target_user_phone = serializers.SerializerMethodField()
    target_role_name = serializers.SerializerMethodField()
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AdminLog
        fields = [
            'id', 'admin', 'admin_name', 'admin_phone',
            'action', 'action_display',
            'target_user', 'target_user_name', 'target_user_phone',
            'target_role', 'target_role_name',
            'details', 'ip_address', 'user_agent', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_admin_name(self, obj):
        if obj.admin:
            return obj.admin.full_name or obj.admin.phone
        return None

    def get_admin_phone(self, obj):
        if obj.admin:
            return obj.admin.phone
        return None

    def get_target_user_name(self, obj):
        if obj.target_user:
            return obj.target_user.full_name or obj.target_user.phone
        return None

    def get_target_user_phone(self, obj):
        if obj.target_user:
            return obj.target_user.phone
        return None

    def get_target_role_name(self, obj):
        if obj.target_role:
            return obj.target_role.name
        return None