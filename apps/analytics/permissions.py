from rest_framework import permissions

from apps.rbac.utils import has_permission

VIEW_PLATFORM_ANALYTICS = "view_platform_analytics"
EXPORT_ANALYTICS = "export_analytics"
MANAGE_ANALYTICS_REPORTS = "manage_analytics_reports"
MANAGE_ANALYTICS_SCHEDULES = "manage_analytics_schedules"


def has_analytics_permission(user, codename):
    if not user:
        return False

    if not user.is_authenticated:
        return False

    if not user.is_active:
        return False

    return has_permission(user, codename)


class AnalyticsPermission(permissions.BasePermission):
    permission_codename = None
    message = "You do not have the required analytics permission."

    def has_permission(self, request, view):
        if not self.permission_codename:
            return False

        return has_analytics_permission(
            request.user,
            self.permission_codename,
        )


class CanViewPlatformAnalytics(AnalyticsPermission):
    permission_codename = VIEW_PLATFORM_ANALYTICS


class CanExportAnalytics(AnalyticsPermission):
    permission_codename = EXPORT_ANALYTICS


class CanManageAnalyticsReports(AnalyticsPermission):
    permission_codename = MANAGE_ANALYTICS_REPORTS


class CanManageAnalyticsSchedules(AnalyticsPermission):
    permission_codename = MANAGE_ANALYTICS_SCHEDULES


# Backward-compatible name for older imports.
# The check is now RBAC-based instead of Django is_staff.
class IsAnalyticsAdmin(CanViewPlatformAnalytics):
    pass
