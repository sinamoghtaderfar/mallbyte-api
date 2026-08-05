from django.core.cache import cache


PERMISSION_CACHE_TIMEOUT = 3600


def get_permissions_cache_key(user):
    return f"user_permissions_{user.id}"


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
    """Get all permissions for a user with caching."""
    if user.is_anonymous:
        return []

    cache_key = get_permissions_cache_key(user)
    cached_permissions = cache.get(cache_key)

    if cached_permissions is not None:
        return cached_permissions

    if user.is_superuser:
        from .models import Permission

        permissions = list(
            Permission.objects.order_by("codename").values_list("codename", flat=True)
        )

    else:
        permissions_set = set()

        user_roles = user.user_roles.select_related("role").prefetch_related(
            "role__role_permissions__permission"
        ).filter(
            is_active=True
        )

        for user_role in user_roles:
            if user_role.is_expired:
                continue

            for role_permission in user_role.role.role_permissions.all():
                permissions_set.add(role_permission.permission.codename)

        permissions = sorted(permissions_set)

    cache.set(cache_key, permissions, PERMISSION_CACHE_TIMEOUT)

    return permissions


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
    if user.is_anonymous:
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