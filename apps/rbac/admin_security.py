"""Django-admin boundaries for identity and authorization policy changes."""


class SuperuserMutationAdminMixin:
    """Delegated model permissions must not become permission-grant authority."""

    def has_add_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser and super().has_add_permission(request))

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser and super().has_change_permission(request, obj))

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser and super().has_delete_permission(request, obj))
