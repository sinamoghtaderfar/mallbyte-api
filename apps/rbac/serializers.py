from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import AdminLog, Permission, Role, RolePermission, UserRole

User = get_user_model()


class DatabaseIdField(serializers.IntegerField):
    """A single positive signed-bigint identifier, never a Boolean or container."""

    def __init__(self, **kwargs):
        super().__init__(min_value=1, max_value=2**63 - 1, **kwargs)

    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (int, str)):
            self.fail("invalid")
        if isinstance(data, str) and not data.strip().isdecimal():
            self.fail("invalid")
        return super().to_internal_value(data)


class SingleValueQuerySerializer(serializers.Serializer):
    """Reject repeated recognized filters instead of silently taking the last."""

    def to_internal_value(self, data):
        if hasattr(data, "getlist"):
            errors = {
                name: ["Provide exactly one value."]
                for name in self.fields
                if len(data.getlist(name)) > 1
            }
            if errors:
                raise serializers.ValidationError(errors)
            # Query strings contain explicit values, not HTML checkbox forms.
            # Otherwise BooleanField supplies False for an omitted filter.
            data = dict(data.items())
        return super().to_internal_value(data)


class UserRoleFilterSerializer(SingleValueQuerySerializer):
    user_id = DatabaseIdField(required=False)
    role_id = DatabaseIdField(required=False)
    is_active = serializers.BooleanField(required=False)


class AdminLogFilterSerializer(SingleValueQuerySerializer):
    admin_id = DatabaseIdField(required=False)
    target_user = DatabaseIdField(required=False)
    action = serializers.CharField(required=False, max_length=100)


class RolePermissionIdSerializer(serializers.Serializer):
    permission_id = DatabaseIdField()


class ConsoleRolePermissionSerializer(RolePermissionIdSerializer):
    enabled = serializers.BooleanField()

    def validate_enabled(self, value):
        # The console contract requires JSON booleans, not truthy strings/IDs.
        if not isinstance(self.initial_data.get("enabled"), bool):
            raise serializers.ValidationError("Expected boolean.")
        return value


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

    def _permission_codenames(self, obj):
        if not hasattr(self, "_permission_names"):
            self._permission_names = {}
        if obj.pk not in self._permission_names:
            links = obj.role_permissions.all()
            if "role_permissions" not in getattr(obj, "_prefetched_objects_cache", {}):
                links = links.select_related("permission")
            self._permission_names[obj.pk] = [link.permission.codename for link in links]
        return self._permission_names[obj.pk]

    def get_permissions(self, obj):
        return self._permission_codenames(obj)

    def get_permissions_count(self, obj):
        return len(self._permission_codenames(obj))


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

    user_id = DatabaseIdField()
    role_id = DatabaseIdField()
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
        child=DatabaseIdField(),
        allow_empty=False,
    )
    role_ids = serializers.ListField(
        child=DatabaseIdField(),
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

    user_id = DatabaseIdField()
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
