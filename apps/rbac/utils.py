from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone


def get_permissions_cache_key(user):
    return f"user_permissions_v3_{user.id}"


def get_user_roles(user):
    """Get all active and non-expired roles for a user."""
    if user.is_anonymous:
        return []

    return [
        user_role
        for user_role in user.user_roles.select_related("role").filter(is_active=True)
        if not user_role.is_expired
    ]


def get_user_permissions(user):
    """Read authorization from the database, including inside transactions.

    Shared result caches can retain grants after rollback or publish stale grants
    after a concurrent revocation. A single DISTINCT join avoids those races.
    """
    if not user.is_authenticated or not user.is_active or user.is_deleted:
        return []

    from .models import Permission

    permissions = Permission.objects.all()
    if not user.is_superuser:
        permissions = permissions.filter(
            Q(permission_roles__role__role_users__expires_at__isnull=True)
            | Q(permission_roles__role__role_users__expires_at__gt=timezone.now()),
            permission_roles__role__role_users__user_id=user.pk,
            permission_roles__role__role_users__is_active=True,
        )
    return list(permissions.order_by("codename").values_list("codename", flat=True).distinct())


def clear_user_permissions_cache(user):
    """Clear cached permissions for a user."""
    cache.delete(get_permissions_cache_key(user))


def clear_role_permissions_cache(role):
    """Clear permissions cache for all active users assigned to a role."""
    user_roles = role.role_users.select_related("user").filter(is_active=True)

    for user_role in user_roles:
        clear_user_permissions_cache(user_role.user)


def has_permission(user, permission_codename):
    """Check if user has a specific permission."""
    if not user.is_authenticated or not user.is_active or user.is_deleted:
        return False

    if user.is_superuser:
        return True

    return permission_codename in get_user_permissions(user)


def assign_role(user, role, assigned_by=None, expires_at=None):
    """Assign a role to a user."""
    from .models import UserRole

    user_role, created = UserRole.objects.get_or_create(
        user=user,
        role=role,
        defaults={
            "assigned_by": assigned_by,
            "expires_at": expires_at,
            "is_active": True,
        },
    )

    if not created:
        user_role.is_active = True
        user_role.expires_at = expires_at
        user_role.assigned_by = assigned_by
        user_role.save(
            update_fields=[
                "is_active",
                "expires_at",
                "assigned_by",
            ]
        )

    clear_user_permissions_cache(user)

    return user_role


def remove_role(user, role):
    """Remove a role from a user."""
    from .models import UserRole

    UserRole.objects.filter(
        user=user,
        role=role,
    ).delete()

    clear_user_permissions_cache(user)


def sync_user_permissions(user):
    """Refresh a user's permission cache."""
    clear_user_permissions_cache(user)


def get_client_ip(request):
    """Get client IP from request."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")


def log_admin_action(
    admin,
    action,
    target_user=None,
    target_role=None,
    details=None,
    request=None,
):
    """Log an admin action."""
    from .models import AdminLog

    log_data = {
        "admin": admin,
        "action": action,
        "target_user": target_user,
        "target_role": target_role,
        "details": details or {},
    }

    if request:
        log_data["ip_address"] = get_client_ip(request)
        log_data["user_agent"] = request.META.get("HTTP_USER_AGENT", "")

    return AdminLog.objects.create(**log_data)