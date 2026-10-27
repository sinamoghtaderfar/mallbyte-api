"""CMS permissions: role-based editorial workflow, independent of Django staff."""
from rest_framework.permissions import BasePermission
from apps.rbac.utils import has_permission

VIEW = "view_content_drafts"
EDIT = "manage_content"
PUBLISH = "publish_content"


def content_has(user, codename):
    return bool(
        user and user.is_authenticated and user.is_active
        and not getattr(user, "is_deleted", False)
        and has_permission(user, codename)
    )


class ContentPermission(BasePermission):
    message = "Your account does not have the required CMS permission."

    def __init__(self, codename=EDIT):
        self.codename = codename

    def has_permission(self, request, view):
        return content_has(request.user, self.codename)

    def has_object_permission(self, request, view, obj):
        # Editing/deleting already-published content is equivalent to changing
        # the public storefront, so it requires publishing authority.
        if view.action in ("update", "partial_update", "destroy"):
            publicly_visible = (
                getattr(obj, "status", None) == "published"
                or (not hasattr(obj, "status") and getattr(obj, "is_active", False))
            )
            if publicly_visible:
                return content_has(request.user, PUBLISH)
        return True


# Backwards-compatible symbol; new policy is RBAC rather than is_staff.
class IsContentAdmin(ContentPermission):
    pass
