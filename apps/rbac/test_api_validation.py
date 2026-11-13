"""RBAC inputs fail at the API boundary and list cost stays independent of rows."""
from urllib.parse import urlencode

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.rbac.models import AdminLog, Permission, Role, RolePermission, UserRole
from apps.rbac.serializers import RoleSerializer


class RBACInputValidationTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="rbac-input-admin@example.com", password="StrongPass123!")
        self.customer = User.objects.create_user(email="rbac-input-customer@example.com")
        self.role = Role.objects.create(name="rbac-input-role")
        self.permission = Permission.objects.create(name="Read input", codename="read_input", module="rbac")
        self.client.force_authenticate(self.admin)

    def test_permission_mutation_rejects_non_scalar_boolean_and_out_of_range_ids(self):
        invalid = ("malformed", [], [self.permission.pk], {}, True, False, 0, -1, 1.5, "1.0", 2**63, None)
        endpoints = (
            ("post", f"/api/rbac/console/roles/{self.role.pk}/permissions/", {"enabled": True}),
            ("post", f"/api/rbac/roles/{self.role.pk}/add_permission/", {}),
            ("delete", f"/api/rbac/roles/{self.role.pk}/remove_permission/", {}),
        )
        for method, endpoint, extra in endpoints:
            for value in invalid:
                with self.subTest(endpoint=endpoint, value=value):
                    response = getattr(self.client, method)(endpoint, {"permission_id": value, **extra}, format="json")
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn("permission_id", response.data)
        self.assertFalse(RolePermission.objects.filter(role=self.role).exists())

    def test_console_preserves_strict_json_boolean_contract_and_valid_numeric_strings(self):
        url = f"/api/rbac/console/roles/{self.role.pk}/permissions/"
        for invalid in ("true", "false", 1, 0, [], {}):
            with self.subTest(enabled=invalid):
                response = self.client.post(url, {"permission_id": self.permission.pk, "enabled": invalid}, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("enabled", response.data)
        response = self.client.post(url, {"permission_id": str(self.permission.pk), "enabled": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(RolePermission.objects.filter(role=self.role, permission=self.permission).exists())
        self.assertEqual(response.data["permissions_count"], len(response.data["permissions"]))

    def test_numeric_query_filters_reject_invalid_and_repeated_values(self):
        endpoints = (
            ("/api/rbac/user-roles/", "user_id"),
            ("/api/rbac/user-roles/", "role_id"),
            ("/api/rbac/admin-logs/", "admin_id"),
            ("/api/rbac/admin-logs/", "target_user"),
        )
        for endpoint, field in endpoints:
            for value in ("abc", "true", "false", "1.5", "[]", "-1", "0", str(2**63)):
                with self.subTest(endpoint=endpoint, field=field, value=value):
                    response = self.client.get(f"{endpoint}?{urlencode({field: value})}")
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn(field, response.data)
            repeated = self.client.get(f"{endpoint}?{field}=1&{field}=2")
            self.assertEqual(repeated.status_code, 400, repeated.data)
            self.assertIn(field, repeated.data)

    def test_valid_filters_preserve_paginated_results_and_boolean_filtering(self):
        assignment = UserRole.objects.create(user=self.customer, role=self.role, assigned_by=self.admin)
        other = Role.objects.create(name="rbac-inactive-role")
        UserRole.objects.create(user=self.customer, role=other, is_active=False, assigned_by=self.admin)
        url = f"/api/rbac/user-roles/?user_id={self.customer.pk}&role_id={self.role.pk}&is_active=true"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], assignment.pk)
        unfiltered = self.client.get(f"/api/rbac/user-roles/?user_id={self.customer.pk}")
        self.assertEqual(unfiltered.status_code, 200, unfiltered.data)
        self.assertEqual(unfiltered.data["count"], 2)
        self.assertIn(assignment.pk, {row["id"] for row in unfiltered.data["results"]})
        inactive = self.client.get("/api/rbac/user-roles/?is_active=false")
        self.assertEqual(inactive.status_code, 200)
        self.assertEqual(inactive.data["count"], 1)
        self.assertEqual(self.client.get("/api/rbac/user-roles/?is_active=typo").status_code, 400)
        log = AdminLog.objects.create(admin=self.admin, target_user=self.customer, action="assign_role")
        logs = self.client.get(f"/api/rbac/admin-logs/?admin_id={self.admin.pk}&target_user={self.customer.pk}&action=assign_role")
        self.assertEqual(logs.status_code, 200, logs.data)
        self.assertEqual(logs.data["count"], 1)
        self.assertEqual(logs.data["results"][0]["id"], log.pk)

    def test_other_role_input_serializers_reject_boolean_container_and_overflow_ids(self):
        endpoints = (
            ("/api/rbac/assign-role/", "user_id", {"role_id": self.role.pk}),
            ("/api/rbac/check-permission/", "user_id", {"permission": self.permission.codename}),
        )
        for endpoint, field, extra in endpoints:
            for value in (True, [], "bad", 2**63):
                with self.subTest(endpoint=endpoint, value=value):
                    response = self.client.post(endpoint, {field: value, **extra}, format="json")
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn(field, response.data)
        for value in (True, [], "bad", 2**63):
            response = self.client.post("/api/rbac/bulk-assign/", {"user_ids": [value], "role_ids": [self.role.pk]}, format="json")
            self.assertEqual(response.status_code, 400, response.data)

    def test_invalid_inputs_do_not_change_the_superuser_authorization_boundary(self):
        self.client.force_authenticate(self.customer)
        for endpoint in ("/api/rbac/user-roles/?user_id=invalid", "/api/rbac/admin-logs/?admin_id=invalid"):
            self.assertEqual(self.client.get(endpoint).status_code, 403)
        response = self.client.post(
            f"/api/rbac/console/roles/{self.role.pk}/permissions/",
            {"permission_id": self.permission.pk, "enabled": True}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(RolePermission.objects.filter(role=self.role).exists())


class RBACRoleQueryTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="rbac-query-admin@example.com", password="StrongPass123!")
        self.client.force_authenticate(self.admin)
        self.permission = Permission.objects.create(name="Role query", codename="role_query", module="rbac")

    def create_roles(self, start, stop):
        for number in range(start, stop):
            role = Role.objects.create(name=f"rbac-query-{number}")
            RolePermission.objects.create(role=role, permission=self.permission)

    def test_role_list_and_console_catalog_use_constant_queries(self):
        self.create_roles(0, 1)
        endpoints = ("/api/rbac/roles/?page_size=100", "/api/rbac/console/role-catalog/")
        first_counts = {}
        for endpoint in endpoints:
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 200, response.data)
            first_counts[endpoint] = len(queries)
        self.create_roles(1, 10)
        for endpoint in endpoints:
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(endpoint)
                self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(queries), first_counts[endpoint], endpoint)
            roles = response.data["results"] if "results" in response.data else response.data["roles"]
            for role in roles:
                self.assertEqual(role["permissions_count"], len(role["permissions"]))

    def test_single_role_serialization_reads_links_once_without_prefetch(self):
        role = Role.objects.create(name="unprefetched-query-role")
        RolePermission.objects.create(role=role, permission=self.permission)
        with self.assertNumQueries(1):
            data = RoleSerializer(role).data
        self.assertEqual(data["permissions"], [self.permission.codename])
        self.assertEqual(data["permissions_count"], 1)
