def get_user_roles(user):
    """Get all active roles for a user"""
    return user.user_roles.filter(is_active=True)


def get_user_permissions(user):
    """Get all permissions for a user"""
    if user.is_superuser:
        
        from .models import Permission
        return list(Permission.objects.values_list('codename', flat=True))
    
    permissions = set()
    for user_role in user.user_roles.filter(is_active=True):
        if user_role.is_expired:
            continue
        for role_perm in user_role.role.role_permissions.all():
            permissions.add(role_perm.permission.codename)
    return list(permissions)


def has_permission(user, permission_codename):
    """Check if user has a specific permission"""
    if user.is_superuser:
        return True
    return permission_codename in get_user_permissions(user)


def assign_role(user, role, assigned_by=None, expires_at=None):
    """Assign a role to a user"""
    from .models import UserRole
    user_role, created = UserRole.objects.get_or_create(
        user=user,
        role=role,
        defaults={
            'assigned_by': assigned_by,
            'expires_at': expires_at,
            'is_active': True
        }
    )
    if not created:
        user_role.is_active = True
        user_role.expires_at = expires_at
        user_role.assigned_by = assigned_by
        user_role.save()
    return user_role


def remove_role(user, role):
    """Remove a role from a user"""
    from .models import UserRole
    UserRole.objects.filter(user=user, role=role).delete()


def sync_user_permissions(user):
    """Sync user permissions (clear cache if needed)"""
    # For future implementation with cache
    pass
from .models import AdminLog

def get_client_ip(request):
    """Get client IP from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def log_admin_action(admin, action, target_user=None, target_role=None, details=None, request=None):
    """Log an admin action"""
    log_data = {
        'admin': admin,
        'action': action,
        'target_user': target_user,
        'target_role': target_role,
        'details': details or {},
    }
    
    if request:
        log_data['ip_address'] = get_client_ip(request)
        log_data['user_agent'] = request.META.get('HTTP_USER_AGENT', '')
    
    return AdminLog.objects.create(**log_data)