from rest_framework import permissions

from apps.rbac.utils import has_permission as rbac_has_permission

VIEW_ALL_SUPPORT_TICKETS = "view_all_support_tickets"
REPLY_SUPPORT_TICKETS = "reply_support_tickets"
VIEW_SUPPORT_INTERNAL_NOTES = "view_support_internal_notes"
ADD_SUPPORT_INTERNAL_NOTE = "add_support_internal_note"
ASSIGN_SUPPORT_TICKETS = "assign_support_tickets"
MANAGE_SUPPORT_TAGS = "manage_support_tags"
CHANGE_SUPPORT_PRIORITY = "change_support_priority"
RESOLVE_SUPPORT_TICKETS = "resolve_support_tickets"
CLOSE_SUPPORT_TICKETS = "close_support_tickets"
REOPEN_SUPPORT_TICKETS = "reopen_support_tickets"
VIEW_SUPPORT_AUDIT_LOGS = "view_support_audit_logs"


def has_support_permission(user, codename):
    if not user or not user.is_authenticated:
        return False

    return rbac_has_permission(
        user,
        codename,
    )


def is_support_staff(user):
    """
    Backwards-compatible helper.

    A support user is now defined by permission rather than
    by a hard-coded role name.
    """
    return has_support_permission(
        user,
        VIEW_ALL_SUPPORT_TICKETS,
    )


def can_be_assigned_support_ticket(user):
    return has_support_permission(
        user,
        VIEW_ALL_SUPPORT_TICKETS,
    ) and has_support_permission(
        user,
        REPLY_SUPPORT_TICKETS,
    )


class IsSupportStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        return is_support_staff(request.user)


class IsTicketParticipantOrSupportStaff(permissions.BasePermission):
    def has_object_permission(
        self,
        request,
        view,
        obj,
    ):
        if not request.user or not request.user.is_authenticated:
            return False

        if obj.customer_id == request.user.id:
            return True

        return has_support_permission(
            request.user,
            VIEW_ALL_SUPPORT_TICKETS,
        )


class CanRespondToSupportTicket(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(
        self,
        request,
        view,
        obj,
    ):
        if obj.customer_id == request.user.id:
            return True

        if not has_support_permission(
            request.user,
            VIEW_ALL_SUPPORT_TICKETS,
        ):
            return False

        return has_support_permission(
            request.user,
            REPLY_SUPPORT_TICKETS,
        ) or has_support_permission(
            request.user,
            ADD_SUPPORT_INTERNAL_NOTE,
        )


class CanAccessSupportAttachments(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(
        self,
        request,
        view,
        obj,
    ):
        if obj.customer_id == request.user.id:
            return True

        if not has_support_permission(
            request.user,
            VIEW_ALL_SUPPORT_TICKETS,
        ):
            return False

        if request.method in permissions.SAFE_METHODS:
            return True

        return has_support_permission(
            request.user,
            REPLY_SUPPORT_TICKETS,
        )


class SupportPermission(permissions.BasePermission):
    permission_codename = None

    def has_permission(self, request, view):
        if not self.permission_codename:
            return False

        return has_support_permission(
            request.user,
            self.permission_codename,
        )


class CanAssignSupportTickets(SupportPermission):
    permission_codename = ASSIGN_SUPPORT_TICKETS


class CanManageSupportTags(SupportPermission):
    permission_codename = MANAGE_SUPPORT_TAGS


class CanChangeSupportPriority(SupportPermission):
    permission_codename = CHANGE_SUPPORT_PRIORITY


class CanResolveSupportTickets(SupportPermission):
    permission_codename = RESOLVE_SUPPORT_TICKETS


class CanCloseSupportTickets(SupportPermission):
    permission_codename = CLOSE_SUPPORT_TICKETS


class CanReopenSupportTickets(SupportPermission):
    permission_codename = REOPEN_SUPPORT_TICKETS


class CanViewSupportAuditLogs(SupportPermission):
    permission_codename = VIEW_SUPPORT_AUDIT_LOGS
