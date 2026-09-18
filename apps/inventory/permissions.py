from rest_framework import permissions

from apps.rbac.utils import has_permission


class CanAccessInventory(permissions.BasePermission):
    """
    Inventory permission policy.

    Read operations require:
        view_inventory

    Write operations require:
        manage_inventory

    Superusers are automatically allowed because
    apps.rbac.utils.has_permission() already handles them.
    """

    view_permission = "view_inventory"
    manage_permission = "manage_inventory"

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in permissions.SAFE_METHODS:
            return has_permission(
                request.user,
                self.view_permission,
            )

        return has_permission(
            request.user,
            self.manage_permission,
        )


class CanAccessStockTransfers(permissions.BasePermission):
    """
    Stock transfer permission policy.

    Read operations require:
        view_inventory

    Write operations require:
        manage_stock_transfers
    """

    view_permission = "view_inventory"
    manage_permission = "manage_stock_transfers"

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in permissions.SAFE_METHODS:
            return has_permission(
                request.user,
                self.view_permission,
            )

        return has_permission(
            request.user,
            self.manage_permission,
        )
