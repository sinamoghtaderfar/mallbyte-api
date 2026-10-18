from rest_framework import permissions

from apps.accounts.models import Seller
from apps.rbac.utils import has_permission

VIEW_PLATFORM_ANALYTICS = "view_platform_analytics"
EXPORT_ANALYTICS = "export_analytics"
MANAGE_ANALYTICS_REPORTS = "manage_analytics_reports"
MANAGE_ANALYTICS_SCHEDULES = "manage_analytics_schedules"
VIEW_SELLER_ANALYTICS = "view_seller_analytics"


def has_analytics_permission(user, codename):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_deleted:
        return False
    return has_permission(user, codename)


class AnalyticsPermission(permissions.BasePermission):
    permission_codename = None
    message = "You do not have the required analytics permission."

    def has_permission(self, request, view):
        return bool(
            self.permission_codename
            and has_analytics_permission(request.user, self.permission_codename)
        )


class CanViewPlatformAnalytics(AnalyticsPermission):
    permission_codename = VIEW_PLATFORM_ANALYTICS


class CanExportAnalytics(AnalyticsPermission):
    permission_codename = EXPORT_ANALYTICS


class CanManageAnalyticsReports(AnalyticsPermission):
    permission_codename = MANAGE_ANALYTICS_REPORTS


class CanManageAnalyticsSchedules(AnalyticsPermission):
    permission_codename = MANAGE_ANALYTICS_SCHEDULES


class CanViewSellerAnalytics(AnalyticsPermission):
    permission_codename = VIEW_SELLER_ANALYTICS

    def has_permission(self, request, view):
        user = request.user
        if not super().has_permission(request, view):
            return False
        if not user.is_seller:
            return False
        return Seller.objects.filter(
            user_id=user.pk,
            status=Seller.StatusChoices.APPROVED,
        ).exists()


class IsAnalyticsAdmin(CanViewPlatformAnalytics):
    """Legacy import alias; not based on is_staff."""

    pass
