from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.rbac.models import AdminLog, Permission, Role, RolePermission


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class SuperAdminConsoleAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="console-owner@example.com", full_name="Owner",
            password="securepass123"
        )
        self.customer = User.objects.create_user(
            email="console-customer@example.com", full_name="Customer",
            password="securepass123"
        )
        self.staff = User.objects.create_user(
            email="console-staff@example.com", full_name="Staff",
            password="securepass123", is_staff=True
        )

    def test_unauthenticated_and_staff_are_denied(self):
        for endpoint in (
            "/api/rbac/console/overview/",
            "/api/rbac/console/users/",
            "/api/rbac/console/products/",
            "/api/rbac/console/role-catalog/",
        ):
            unauthenticated = self.client.get(endpoint)
            self.assertIn(unauthenticated.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
            self.client.force_authenticate(user=self.staff)
            response = self.client.get(endpoint)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.client.force_authenticate(user=None)

    def test_superuser_can_get_overview_and_search_users(self):
        self.client.force_authenticate(user=self.admin)
        dashboard = self.client.get("/api/rbac/console/overview/")
        self.assertEqual(dashboard.status_code, status.HTTP_200_OK)
        self.assertEqual(dashboard.data["users"], 3)
        response = self.client.get("/api/rbac/console/users/?search=console-customer")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.customer.id)

    def test_customer_cannot_change_status(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post(
            f"/api/rbac/console/users/{self.staff.pk}/set-status/",
            {"is_active": False, "reason": "Not authorized"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_superuser_cannot_lock_staff_or_other_superusers(self):
        self.client.force_authenticate(user=self.admin)
        for user in (self.admin, self.staff):
            response = self.client.post(
                f"/api/rbac/console/users/{user.pk}/set-status/",
                {"is_active": False, "reason": "Attempted change"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            user.refresh_from_db()
            self.assertTrue(user.is_active)

    def test_suspend_requires_reason_and_records_audit(self):
        self.client.force_authenticate(user=self.admin)
        url = f"/api/rbac/console/users/{self.customer.pk}/set-status/"
        invalid = self.client.post(url, {"is_active": False, "reason": "no"}, format="json")
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)
        valid = self.client.post(
            url, {"is_active": False, "reason": "Confirmed abuse"}, format="json"
        )
        self.assertEqual(valid.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        log = AdminLog.objects.get(action="suspend_user", target_user=self.customer)
        self.assertEqual(log.details["reason"], "Confirmed abuse")

    def test_role_permission_changes_require_superuser_and_are_audited(self):
        role = Role.objects.create(name="support_lead", level=20)
        system_role = Role.objects.create(name="customer", is_system_role=True)
        permission = Permission.objects.create(
            name="View test", codename="view_console_test", module="rbac"
        )
        url = f"/api/rbac/console/roles/{role.pk}/permissions/"
        payload = {"permission_id": permission.pk, "enabled": True}
        self.client.force_authenticate(user=self.staff)
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 403)
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(
            self.client.post(
                f"/api/rbac/console/roles/{system_role.pk}/permissions/", payload, format="json"
            ).status_code, 403
        )
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 200)
        self.assertTrue(RolePermission.objects.filter(role=role, permission=permission).exists())
        self.assertTrue(AdminLog.objects.filter(action="change_permission", target_role=role).exists())
        payload["enabled"] = False
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 200)
        self.assertFalse(RolePermission.objects.filter(role=role, permission=permission).exists())
