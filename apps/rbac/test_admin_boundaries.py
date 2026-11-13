from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group, Permission
from django.test import RequestFactory, TestCase

from apps.accounts.admin import GroupAdmin, OTPAdmin, UserAdmin
from apps.accounts.models import OTP, User
from apps.rbac.admin import AdminLogAdmin, PermissionAdmin, RoleAdmin, RolePermissionAdmin, UserRoleAdmin
from apps.rbac.models import AdminLog, Role, RolePermission, UserRole
from apps.rbac.models import Permission as BusinessPermission


class DjangoAdminPrivilegeBoundaryTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(email="delegated@example.com", is_staff=True)
        self.superuser = User.objects.create_superuser(email="super@example.com", password="admin-password")
        # Reproduce a delegated operator with every Django model capability.
        # This must not be equivalent to authority to grant itself more access.
        self.staff.user_permissions.set(Permission.objects.all())
        self.factory = RequestFactory()
        self.site = AdminSite()

    def request(self, actor):
        request = self.factory.post("/admin/")
        request.user = actor
        return request

    def sensitive_admins(self):
        return [
            UserAdmin(User, self.site), GroupAdmin(Group, self.site),
            RoleAdmin(Role, self.site), PermissionAdmin(BusinessPermission, self.site),
            RolePermissionAdmin(RolePermission, self.site), UserRoleAdmin(UserRole, self.site),
        ]

    def test_delegated_model_permissions_cannot_mutate_identity_or_authorization(self):
        request = self.request(self.staff)
        for model_admin in self.sensitive_admins():
            with self.subTest(model=model_admin.model._meta.label):
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(model_admin.has_change_permission(request, self.staff))
                self.assertFalse(model_admin.has_delete_permission(request, self.staff))
                self.assertTrue(model_admin.has_view_permission(request))

    def test_superuser_retains_identity_and_policy_management(self):
        request = self.request(self.superuser)
        for model_admin in self.sensitive_admins():
            with self.subTest(model=model_admin.model._meta.label):
                self.assertTrue(model_admin.has_add_permission(request))
                self.assertTrue(model_admin.has_change_permission(request))
                self.assertTrue(model_admin.has_delete_permission(request))

    def test_delegated_operator_cannot_view_plaintext_otp(self):
        model_admin = OTPAdmin(OTP, self.site)
        self.assertFalse(model_admin.has_view_permission(self.request(self.staff)))
        self.assertFalse(model_admin.has_change_permission(self.request(self.staff)))
        self.assertTrue(model_admin.has_view_permission(self.request(self.superuser)))
        self.assertFalse(model_admin.has_change_permission(self.request(self.superuser)))

    def test_audit_logs_cannot_be_created_changed_or_deleted_in_admin(self):
        model_admin = AdminLogAdmin(AdminLog, self.site)
        for actor in (self.staff, self.superuser):
            request = self.request(actor)
            self.assertTrue(model_admin.has_view_permission(request))
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))

    def test_password_change_admin_view_is_denied_to_delegated_operator(self):
        model_admin = UserAdmin(User, self.site)
        request = self.request(self.staff)
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            model_admin.user_change_password(request, str(self.superuser.pk))
