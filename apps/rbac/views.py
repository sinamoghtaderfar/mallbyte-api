from django.contrib.auth import get_user_model
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import AdminLog, Permission, Role, RolePermission, UserRole
from .permissions import IsSuperAdmin
from .serializers import (
    AdminLogSerializer,
    AssignRoleSerializer,
    BulkAssignRoleSerializer,
    CheckPermissionSerializer,
    PermissionSerializer,
    RolePermissionSerializer,
    RoleSerializer,
    UserPermissionsSerializer,
    UserRoleSerializer,
)
from .utils import (
    assign_role,
    clear_role_permissions_cache,
    get_user_permissions,
    has_permission,
    log_admin_action,
    remove_role,
)

User = get_user_model()


class RoleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing roles."""

    serializer_class = RoleSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        queryset = Role.objects.prefetch_related(
            "role_permissions__permission",
        ).all()

        name = self.request.query_params.get("name")
        if name:
            queryset = queryset.filter(name__icontains=name)

        return queryset

    def update(self, request, *args, **kwargs):
        role = self.get_object()

        if role.is_system_role and "name" in request.data:
            return Response(
                {
                    "error": "System role name cannot be changed"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        role = self.get_object()

        if role.is_system_role and "name" in request.data:
            return Response(
                {
                    "error": "System role name cannot be changed"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        role = self.get_object()

        if role.is_system_role:
            return Response(
                {
                    "error": "System roles cannot be deleted"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"])
    def permissions(self, request, pk=None):
        """Get all permissions for a role."""
        role = self.get_object()
        role_permissions = role.role_permissions.select_related("permission").all()
        serializer = RolePermissionSerializer(role_permissions, many=True)

        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def add_permission(self, request, pk=None):
        """Add a permission to a role."""
        role = self.get_object()
        permission_id = request.data.get("permission_id")

        try:
            permission = Permission.objects.get(id=permission_id)

        except Permission.DoesNotExist:
            return Response(
                {
                    "error": "Permission not found"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        role_permission, created = RolePermission.objects.get_or_create(
            role=role,
            permission=permission,
        )

        clear_role_permissions_cache(role)

        if created:
            return Response(
                {
                    "message": "Permission added"
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            {
                "message": "Permission already exists"
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["delete"])
    def remove_permission(self, request, pk=None):
        """Remove a permission from a role."""
        role = self.get_object()
        permission_id = request.data.get("permission_id")

        try:
            permission = Permission.objects.get(id=permission_id)

        except Permission.DoesNotExist:
            return Response(
                {
                    "error": "Permission not found"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        RolePermission.objects.filter(
            role=role,
            permission=permission,
        ).delete()

        clear_role_permissions_cache(role)

        return Response(
            {
                "message": "Permission removed"
            },
            status=status.HTTP_200_OK,
        )


class PermissionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing permissions."""

    serializer_class = PermissionSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        queryset = Permission.objects.all()

        module = self.request.query_params.get("module")
        if module:
            queryset = queryset.filter(module=module)

        return queryset


class UserRoleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing user roles."""

    serializer_class = UserRoleSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        queryset = UserRole.objects.select_related(
            "user",
            "role",
            "assigned_by",
        ).all()

        user_id = self.request.query_params.get("user_id")
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        role_id = self.request.query_params.get("role_id")
        if role_id:
            queryset = queryset.filter(role_id=role_id)

        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == "true")

        return queryset


class AssignRoleView(generics.GenericAPIView):
    """Assign one role to one user."""

    permission_classes = [IsSuperAdmin]
    serializer_class = AssignRoleSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.get(id=serializer.validated_data["user_id"])
        role = Role.objects.get(id=serializer.validated_data["role_id"])
        expires_at = serializer.validated_data.get("expires_at")

        user_role = assign_role(
            user=user,
            role=role,
            assigned_by=request.user,
            expires_at=expires_at,
        )

        log_admin_action(
            admin=request.user,
            action="assign_role",
            target_user=user,
            target_role=role,
            details={
                "role_name": role.name,
                "expires_at": str(expires_at) if expires_at else None,
                "user_role_id": user_role.id,
            },
            request=request,
        )

        return Response(
            UserRoleSerializer(user_role).data,
            status=status.HTTP_201_CREATED,
        )


class RemoveRoleView(generics.GenericAPIView):
    """Remove a role from a user."""

    permission_classes = [IsSuperAdmin]

    def delete(self, request, user_id, role_id):
        try:
            user = User.objects.get(id=user_id)
            role = Role.objects.get(id=role_id)

        except (User.DoesNotExist, Role.DoesNotExist):
            return Response(
                {
                    "error": "User or role not found"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        remove_role(user, role)

        log_admin_action(
            admin=request.user,
            action="remove_role",
            target_user=user,
            target_role=role,
            details={
                "role_name": role.name
            },
            request=request,
        )

        return Response(
            {
                "message": "Role removed successfully"
            },
            status=status.HTTP_200_OK,
        )


class UserPermissionsView(generics.GenericAPIView):
    """Get permissions for a specific user."""

    permission_classes = [IsSuperAdmin]

    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)

        except User.DoesNotExist:
            return Response(
                {
                    "error": "User not found"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        permissions = get_user_permissions(user)

        serializer = UserPermissionsSerializer(
            {
                "user_id": user.id,
                "user_email": user.email,
                "permissions": permissions,
                "permissions_count": len(permissions),
            }
        )

        return Response(serializer.data)


class MyPermissionsView(generics.GenericAPIView):
    """Get current user's permissions."""

    def get_permissions(self):
        from rest_framework.permissions import IsAuthenticated

        return [IsAuthenticated()]

    def get(self, request):
        permissions = get_user_permissions(request.user)

        return Response(
            {
                "user_id": request.user.id,
                "email": request.user.email,
                "permissions": permissions,
                "permissions_count": len(permissions),
            }
        )


class CheckPermissionView(generics.GenericAPIView):
    """Check if a user has a specific permission."""

    permission_classes = [IsSuperAdmin]
    serializer_class = CheckPermissionSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.get(id=serializer.validated_data["user_id"])
        permission_codename = serializer.validated_data["permission"]

        return Response(
            {
                "user_id": user.id,
                "user_email": user.email,
                "permission": permission_codename,
                "has_permission": has_permission(user, permission_codename),
            }
        )


class AdminLogListView(generics.ListAPIView):
    """View for admins to see all action logs."""

    permission_classes = [IsSuperAdmin]
    serializer_class = AdminLogSerializer

    def get_queryset(self):
        queryset = AdminLog.objects.select_related(
            "admin",
            "target_user",
            "target_role",
        ).all()

        admin_id = self.request.query_params.get("admin_id")
        if admin_id:
            queryset = queryset.filter(admin_id=admin_id)

        target_user_id = self.request.query_params.get("target_user")
        if target_user_id:
            queryset = queryset.filter(target_user_id=target_user_id)

        action_value = self.request.query_params.get("action")
        if action_value:
            queryset = queryset.filter(action=action_value)

        return queryset


class AdminLogDetailView(generics.RetrieveAPIView):
    """View for admins to see a specific log entry."""

    permission_classes = [IsSuperAdmin]
    serializer_class = AdminLogSerializer

    def get_queryset(self):
        return AdminLog.objects.select_related(
            "admin",
            "target_user",
            "target_role",
        ).all()


class BulkAssignRolesView(generics.GenericAPIView):
    """Bulk assign multiple roles to multiple users."""

    permission_classes = [IsSuperAdmin]
    serializer_class = BulkAssignRoleSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_ids = serializer.validated_data["user_ids"]
        role_ids = serializer.validated_data["role_ids"]
        expires_at = serializer.validated_data.get("expires_at")

        users = User.objects.filter(id__in=user_ids)
        roles = Role.objects.filter(id__in=role_ids)

        results = []
        errors = []

        for user in users:
            for role in roles:
                try:
                    user_role = assign_role(
                        user=user,
                        role=role,
                        assigned_by=request.user,
                        expires_at=expires_at,
                    )

                    results.append(
                        {
                            "user_id": user.id,
                            "user_email": user.email,
                            "role_id": role.id,
                            "role_name": role.name,
                            "user_role_id": user_role.id,
                            "assigned_at": user_role.assigned_at,
                        }
                    )

                    log_admin_action(
                        admin=request.user,
                        action="assign_role",
                        target_user=user,
                        target_role=role,
                        details={
                            "role_name": role.name,
                            "expires_at": str(expires_at) if expires_at else None,
                            "bulk": True,
                        },
                        request=request,
                    )

                except Exception as exc:
                    errors.append(
                        {
                            "user_id": user.id,
                            "user_email": user.email,
                            "role_id": role.id,
                            "role_name": role.name,
                            "error": str(exc),
                        }
                    )

        return Response(
            {
                "success": len(errors) == 0,
                "assigned": results,
                "errors": errors,
                "summary": {
                    "total_users": users.count(),
                    "total_roles": roles.count(),
                    "total_assignments": len(results),
                    "total_errors": len(errors),
                },
            },
            status=status.HTTP_201_CREATED if not errors else status.HTTP_207_MULTI_STATUS,
        )