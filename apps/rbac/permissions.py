from rest_framework import permissions


def user_has_active_role(user, role_name):
    if not user.is_authenticated:
        return False

    user_roles = user.user_roles.filter(
        role__name=role_name,
        is_active=True,
    )

    return any(not user_role.is_expired for user_role in user_roles)


class HasPermission(permissions.BasePermission):
    """Check if user has a specific permission."""

    def __init__(self, permission_codename):
        self.permission_codename = permission_codename

    def has_permission(self, request, view):
        from .utils import has_permission as check_permission

        if not request.user.is_authenticated:
            return False

        return check_permission(request.user, self.permission_codename)


class HasAnyPermission(permissions.BasePermission):
    """Check if user has any of the specified permissions."""

    def __init__(self, *permission_codenames):
        self.permission_codenames = permission_codenames

    def has_permission(self, request, view):
        from .utils import has_permission as check_permission

        if not request.user.is_authenticated:
            return False

        return any(
            check_permission(request.user, permission_codename)
            for permission_codename in self.permission_codenames
        )


class IsSuperAdmin(permissions.BasePermission):
    """Check if user is super admin."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_superuser


class IsVendorManager(permissions.BasePermission):
    """Check if user has vendor manager role."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and (
                request.user.is_superuser
                or user_has_active_role(request.user, "vendor_manager")
            )
        )


class IsContentAdmin(permissions.BasePermission):
    """Check if user has content admin role."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and (
                request.user.is_superuser
                or user_has_active_role(request.user, "content_admin")
            )
        )


class IsProductAdmin(permissions.BasePermission):
    """Check if user has product admin role."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and (
                request.user.is_superuser
                or user_has_active_role(request.user, "product_admin")
            )
        )


class IsVendor(permissions.BasePermission):
    """Check if user is a verified vendor."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        return hasattr(request.user, "seller") and request.user.seller.is_verified


class IsCustomer(permissions.BasePermission):
    """Check if user is a regular customer."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        return (
            not request.user.is_superuser
            and not request.user.is_staff
            and not hasattr(request.user, "seller")
        )