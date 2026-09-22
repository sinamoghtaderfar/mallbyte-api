from rest_framework import permissions

from apps.rbac.utils import has_permission


class CanAccessInventory(permissions.BasePermission):
    """
    General inventory permissions.

    Read: view_inventory
    Write: manage_inventory
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.method in permissions.SAFE_METHODS:
            return has_permission(
                request.user,
                "view_inventory",
            )

        return has_permission(
            request.user,
            "manage_inventory",
        )


class CanAccessStockTransfers(permissions.BasePermission):
    """
    Stock transfer permissions.

    Read: view_inventory
    Create: create_stock_transfers
    Approve / cancel: approve_stock_transfers
    Ship: ship_stock_transfers
    Receive: receive_stock_transfers
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Let DRF return 405 for unsupported methods.
        if request.method not in view.allowed_methods:
            return True

        if request.method in permissions.SAFE_METHODS:
            return has_permission(
                request.user,
                "view_inventory",
            )

        action_permissions = {
            "create": "create_stock_transfers",
            "approve": "approve_stock_transfers",
            "cancel": "approve_stock_transfers",
            "ship": "ship_stock_transfers",
            "receive": "receive_stock_transfers",
        }

        required_permission = action_permissions.get(view.action)

        if required_permission is None:
            return False

        return has_permission(
            request.user,
            required_permission,
        )
