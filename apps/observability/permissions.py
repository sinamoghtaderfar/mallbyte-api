"""Least-privilege observability authorization; staff flags alone grant nothing."""
from rest_framework.permissions import BasePermission
from apps.rbac.utils import has_permission


def allowed(user, codename):
    return bool(
        user and user.is_authenticated and user.is_active
        and (user.is_superuser or has_permission(user, codename))
    )


class IsObservabilityAdmin(BasePermission):
    """Legacy class name retained for existing import compatibility: viewer access."""
    def has_permission(self, request, view):
        return allowed(request.user, "view_observability")


class IsObservabilityLogsReader(BasePermission):
    def has_permission(self, request, view):
        return allowed(request.user, "view_observability_logs")


class IsObservabilityAlertManager(BasePermission):
    def has_permission(self, request, view):
        return allowed(request.user, "manage_observability_alerts")


class IsObservabilityErrorManager(BasePermission):
    def has_permission(self, request, view):
        return allowed(request.user, "resolve_observability_errors")
