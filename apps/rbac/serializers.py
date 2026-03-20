from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Role, Permission, RolePermission, UserRole

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