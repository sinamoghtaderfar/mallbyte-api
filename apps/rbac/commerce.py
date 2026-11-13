"""Commerce capabilities: Django staff membership never grants business access."""
from rest_framework.permissions import BasePermission

from apps.rbac.utils import has_permission


def can_manage(user, domain):
    return has_permission(user, f"manage_{domain}")


def can_view_all(user, domain):
    return can_manage(user, domain) or has_permission(user, f"view_all_{domain}")


class CanManageOrders(BasePermission):
    message = "Order management permission is required."

    def has_permission(self, request, view):
        return can_manage(request.user, "orders")
