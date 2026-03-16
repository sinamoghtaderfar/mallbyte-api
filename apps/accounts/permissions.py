from rest_framework import permissions

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