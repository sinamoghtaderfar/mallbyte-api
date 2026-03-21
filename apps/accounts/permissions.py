from rest_framework import permissions
from apps.rbac.utils import has_permission

class IsAdminOrVendorManager(permissions.BasePermission):
    """
    Allow access only to admin users or vendor managers.
    """
    def has_permission(self, request, view):
         return request.user and (
            request.user.is_staff or 
            request.user.is_superuser or
            request.user.groups.filter(name='Vendor Managers').exists()
        )

class IsVerifiedSeller(permissions.BasePermission):
    """Check if user is a verified seller"""
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        
        # RBAC
        return has_permission(request.user, 'add_product')