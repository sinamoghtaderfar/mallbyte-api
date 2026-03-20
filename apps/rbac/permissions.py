from rest_framework import permissions
from .utils import has_permission as check_permission

class HasPermission(permissions.BasePermission):
    """
    Check if user has a specific permission
    """
    
    def __init__(self, permission_codename):
        self.permission_codename = permission_codename
    
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return check_permission(request.user, self.permission_codename)
    
    
class HasAnyPermission(permissions.BasePermission):
    """
    Check if user has any of the specified permissions
    """
    def __init__(self, *permissions_codenames):
        self.permissions = permissions_codenames

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        for perm in self.permissions:
            if check_permission(request.user, perm):
                return True
        return False


class IsSuperAdmin(permissions.BasePermission):
    """Check if user is super admin"""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_superuser


class IsVendorManager(permissions.BasePermission):
    """Check if user has vendor manager role"""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.user_roles.filter(
            role__name='vendor_manager', 
            is_active=True
        ).exists() or request.user.is_superuser


class IsContentAdmin(permissions.BasePermission):
    """Check if user has content admin role"""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.user_roles.filter(
            role__name='content_admin', 
            is_active=True
        ).exists() or request.user.is_superuser


class IsProductAdmin(permissions.BasePermission):
    """Check if user has product admin role"""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.user_roles.filter(
            role__name='product_admin', 
            is_active=True
        ).exists() or request.user.is_superuser


class IsVendor(permissions.BasePermission):
    """Check if user is a verified vendor"""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return hasattr(request.user, 'seller') and request.user.seller.is_verified


class IsCustomer(permissions.BasePermission):
    """Check if user is a regular customer"""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        # Not super admin, not admin staff, not vendor
        return not request.user.is_superuser and not request.user.is_staff and not hasattr(request.user, 'seller')