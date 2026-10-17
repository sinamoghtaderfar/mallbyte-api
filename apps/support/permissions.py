from rest_framework import permissions

from apps.rbac.permissions import user_has_active_role

SUPPORT_AGENT_ROLE = "support_agent"


def is_support_staff(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user_has_active_role(user, SUPPORT_AGENT_ROLE))
    )


class IsSupportStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        return is_support_staff(request.user)


class IsTicketParticipantOrSupportStaff(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if is_support_staff(request.user):
            return True

        return obj.customer_id == request.user.id
