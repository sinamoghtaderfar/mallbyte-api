from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.rbac.models import RolePermission, UserRole
from apps.rbac.utils import (
    clear_role_permissions_cache,
    clear_user_permissions_cache,
)


@receiver(
    [post_save, post_delete],
    sender=UserRole,
)
def clear_user_role_permission_cache(
    sender,
    instance,
    **kwargs,
):
    if instance.user_id:
        clear_user_permissions_cache(instance.user)


@receiver(
    [post_save, post_delete],
    sender=RolePermission,
)
def clear_role_permission_cache(
    sender,
    instance,
    **kwargs,
):
    if instance.role_id:
        clear_role_permissions_cache(instance.role)
