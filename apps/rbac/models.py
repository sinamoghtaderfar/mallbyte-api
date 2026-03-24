from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone


User = get_user_model()

class Role(models.Model):
    """
    Role model for RBAC - defines different user roles in the system
    """
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, verbose_name="Description")
    level = models.IntegerField(default=0, verbose_name="Role Level", help_text="Higher level = more permissions")
    is_system_role = models.BooleanField(default=False, verbose_name="System Role", help_text="System roles cannot be deleted")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Role"
        verbose_name_plural = "Roles"
        ordering = ['level', 'name']
        
    def __str__(self):
        return self.name
    
class Permission(models.Model):
    """
    Permission model - specific actions users can perform
    """
    name = models.CharField(max_length=255, verbose_name="Permission Name")
    codename = models.CharField(max_length=100, unique=True, verbose_name="Code Name")
    module = models.CharField(max_length=50, verbose_name="Module",
                               choices=[
                                   ('accounts', 'Accounts'),
                                   ('products', 'Products'),
                                   ('orders', 'Orders'),
                                   ('payments', 'Payments'),
                                   ('discounts', 'Discounts'),
                                   ('reviews', 'Reviews'),
                                   ('shipping', 'Shipping'),
                                   ('content', 'Content'),
                                   ('rbac', 'RBAC'),
                               ])
    description = models.TextField(blank=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Permission"
        verbose_name_plural = "Permissions"
        ordering = ['name']
        
    def __str__(self):
        return f"{self.module}.{self.codename}"
    
class RolePermission(models.Model):
    """
    Junction table linking roles to permissions
    """
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='role_permissions')
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='permission_roles')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Role Permission"
        verbose_name_plural = "Role Permissions"
        unique_together = ('role', 'permission')
        
    def __str__(self):
        return f"{self.role.name} -> {self.permission.codename}"
    
class UserRole(models.Model):
    """
    Junction table linking users to roles with assignment tracking
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='role_users')
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='assigned_roles', verbose_name="Assigned By")
    assigned_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Expires At")
    is_active = models.BooleanField(default=True, verbose_name="Is Active")

    class Meta:
        verbose_name = "User Role"
        verbose_name_plural = "User Roles"
        unique_together = ('user', 'role')
        
    def __str__(self):
        return f"{self.user.username} -> {self.role.name}"
    
    @property
    def is_expired(self):
        """Check if role assignment has expired"""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False


class AdminLog(models.Model):
    ACTION_CHOICES = [
        ('assign_role', 'Assign Role'),
        ('remove_role', 'Remove Role'),
        ('approve_seller', 'Approve Seller'),
        ('reject_seller', 'Reject Seller'),
        ('suspend_user', 'Suspend User'),
        ('activate_user', 'Activate User'),
        ('change_permission', 'Change Permission'),
        ('create_role', 'Create Role'),
        ('delete_role', 'Delete Role'),
        ('update_role', 'Update Role'),
    ]
    
    admin = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, related_name='admin_actions')
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    target_user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='targeted_actions')
    target_role = models.ForeignKey('Role', on_delete=models.SET_NULL, null=True, blank=True, related_name='role_actions')
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

