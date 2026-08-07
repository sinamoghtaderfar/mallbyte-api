from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import AdminLog, Permission, Role, RolePermission, UserRole

User = get_user_model()


class RoleSerializer(serializers.ModelSerializer):
    """Serializer for Role model."""

    permissions = serializers.SerializerMethodField()
    permissions_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "description",
            "level",
            "is_system_role",
            "permissions",
            "permissions_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "is_system_role",
        ]

    def get_permissions(self, obj):
        return [
            role_permission.permission.codename
            for role_permission in obj.role_permissions.select_related("permission").all()
        ]

    def get_permissions_count(self, obj):
        return obj.role_permissions.count()


class PermissionSerializer(serializers.ModelSerializer):
    """Serializer for Permission model."""

    class Meta:
        model = Permission
        fields = [
            "id",
            "name",
            "codename",
            "module",
            "description",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]


class RolePermissionSerializer(serializers.ModelSerializer):
    """Serializer for role-permission assignments."""

    role_name = serializers.ReadOnlyField(source="role.name")
    permission_name = serializers.ReadOnlyField(source="permission.name")
    permission_codename = serializers.ReadOnlyField(source="permission.codename")

    class Meta:
        model = RolePermission
        fields = [
            "id",
            "role",
            "role_name",
            "permission",
            "permission_name",
            "permission_codename",
        ]
        read_only_fields = [
            "id",
        ]


class UserRoleSerializer(serializers.ModelSerializer):
    """Serializer for user-role assignments."""

    user_email = serializers.ReadOnlyField(source="user.email")
    user_full_name = serializers.ReadOnlyField(source="user.full_name")
    role_name = serializers.ReadOnlyField(source="role.name")
    role_level = serializers.ReadOnlyField(source="role.level")
    assigned_by_email = serializers.ReadOnlyField(source="assigned_by.email")
    assigned_by_name = serializers.SerializerMethodField()
    is_expired = serializers.ReadOnlyField()

    class Meta:
        model = UserRole
        fields = [
            "id",
            "user",
            "user_email",
            "user_full_name",
            "role",
            "role_name",
            "role_level",
            "assigned_by",
            "assigned_by_email",
            "assigned_by_name",
            "assigned_at",
            "expires_at",
            "is_active",
            "is_expired",
        ]
        read_only_fields = [
            "id",
            "assigned_at",
            "is_expired",
        ]

    def get_assigned_by_name(self, obj):
        if obj.assigned_by:
            return obj.assigned_by.full_name or obj.assigned_by.email

        return None


class AssignRoleSerializer(serializers.Serializer):
    """Serializer for assigning one role to one user."""

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


class BulkAssignRoleSerializer(serializers.Serializer):
    """Serializer for assigning multiple roles to multiple users."""

    user_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
    )
    role_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_user_ids(self, value):
        unique_ids = list(dict.fromkeys(value))
        existing_ids = set(
            User.objects.filter(id__in=unique_ids).values_list("id", flat=True)
        )
        missing_ids = set(unique_ids) - existing_ids

        if missing_ids:
            raise serializers.ValidationError(
                f"Users with IDs {sorted(missing_ids)} do not exist"
            )

        return unique_ids

    def validate_role_ids(self, value):
        unique_ids = list(dict.fromkeys(value))
        existing_ids = set(
            Role.objects.filter(id__in=unique_ids).values_list("id", flat=True)
        )
        missing_ids = set(unique_ids) - existing_ids

        if missing_ids:
            raise serializers.ValidationError(
                f"Roles with IDs {sorted(missing_ids)} do not exist"
            )

        return unique_ids


class CheckPermissionSerializer(serializers.Serializer):
    """Serializer for checking a user permission."""

    user_id = serializers.IntegerField()
    permission = serializers.CharField()

    def validate_user_id(self, value):
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("User does not exist")

        return value


class UserPermissionsSerializer(serializers.Serializer):
    """Serializer for user permissions output."""

    user_id = serializers.IntegerField()
    user_email = serializers.EmailField()
    permissions = serializers.ListField(child=serializers.CharField())
    permissions_count = serializers.IntegerField()


class AdminLogSerializer(serializers.ModelSerializer):
    """Serializer for admin action logs."""

    admin_name = serializers.SerializerMethodField()
    admin_email = serializers.ReadOnlyField(source="admin.email")
    target_user_name = serializers.SerializerMethodField()
    target_user_email = serializers.ReadOnlyField(source="target_user.email")
    target_role_name = serializers.ReadOnlyField(source="target_role.name")
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AdminLog
        fields = [
            "id",
            "admin",
            "admin_name",
            "admin_email",
            "action",
            "action_display",
            "target_user",
            "target_user_name",
            "target_user_email",
            "target_role",
            "target_role_name",
            "details",
            "ip_address",
            "user_agent",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]

    def get_admin_name(self, obj):
        if obj.admin:
            return obj.admin.full_name or obj.admin.email

        return None

    def get_target_user_name(self, obj):
        if obj.target_user:
            return obj.target_user.full_name or obj.target_user.email

        return None