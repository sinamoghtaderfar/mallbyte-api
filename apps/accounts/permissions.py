from rest_framework import permissions

from apps.rbac.utils import has_permission


class IsAdminOrVendorManager(permissions.BasePermission):
    """Seller administration requires an explicit business permission."""

    def has_permission(self, request, view):
        return has_permission(request.user, "view_sellers")


class CanApproveSeller(permissions.BasePermission):
    def has_permission(self, request, view):
        return has_permission(request.user, "approve_seller")


class CanRejectSeller(permissions.BasePermission):
    def has_permission(self, request, view):
        return has_permission(request.user, "reject_seller")


class CanDeleteUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return has_permission(request.user, "delete_user")


class IsVerifiedSeller(permissions.BasePermission):
    """Check if user has permission to create products."""

    def has_permission(self, request, view):
        return has_permission(request.user, "add_product")
