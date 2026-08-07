from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import IntegrityError
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import AdminLog, Permission, Role, RolePermission, UserRole
from .permissions import (
    HasAnyPermission,
    HasPermission,
    IsContentAdmin,
    IsCustomer,
    IsProductAdmin,
    IsSuperAdmin,
    IsVendorManager,
)
from .serializers import AssignRoleSerializer, BulkAssignRoleSerializer
from .utils import (
    assign_role,
    clear_role_permissions_cache,
    clear_user_permissions_cache,
    get_client_ip,
    get_user_permissions,
    get_user_roles,
    has_permission,
    log_admin_action,
    remove_role,
)

User = get_user_model()


class RBACTestMixin:
    def setUp(self):
        cache.clear()

        self.admin = self.create_user(
            email="admin@example.com",
            full_name="Admin User",
            is_staff=True,
            is_superuser=True,
        )
        self.user = self.create_user(
            email="customer@example.com",
            full_name="Customer User",
        )
        self.second_user = self.create_user(
            email="second@example.com",
            full_name="Second User",
        )

        self.role = Role.objects.create(
            name="manager",
            description="Manager role",
            level=10,
        )
        self.vendor_role = Role.objects.create(
            name="vendor_manager",
            description="Vendor manager role",
            level=20,
        )
        self.product_role = Role.objects.create(
            name="product_admin",
            description="Product admin role",
            level=30,
        )
        self.content_role = Role.objects.create(
            name="content_admin",
            description="Content admin role",
            level=40,
        )
        self.system_role = Role.objects.create(
            name="customer",
            description="System customer role",
            level=1,
            is_system_role=True,
        )

        self.permission = Permission.objects.create(
            name="View Products",
            codename="view_products",
            module="products",
            description="Can view products",
        )
        self.second_permission = Permission.objects.create(
            name="Manage Products",
            codename="manage_products",
            module="products",
            description="Can manage products",
        )
        self.content_permission = Permission.objects.create(
            name="Manage Content",
            codename="manage_content",
            module="content",
            description="Can manage content",
        )

    def create_user(
        self,
        email,
        full_name="Test User",
        password="StrongPass123!",
        is_staff=False,
        is_superuser=False,
        is_active=True,
    ):
        user = User(
            email=email,
            full_name=full_name,
            is_staff=is_staff,
            is_superuser=is_superuser,
            is_active=is_active,
        )
        user.set_password(password)
        user.save()
        return user

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.admin)


class RBACModelTestCase(RBACTestMixin, TestCase):
    def test_role_str_returns_name(self):
        self.assertEqual(str(self.role), "manager")

    def test_permission_str_returns_module_and_codename(self):
        self.assertEqual(str(self.permission), "products.view_products")

    def test_role_permission_unique_pair(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )

        with self.assertRaises(IntegrityError):
            RolePermission.objects.create(
                role=self.role,
                permission=self.permission,
            )

    def test_user_role_str_uses_email_identifier(self):
        user_role = UserRole.objects.create(
            user=self.user,
            role=self.role,
            assigned_by=self.admin,
        )

        self.assertIn(self.user.email, str(user_role))
        self.assertIn(self.role.name, str(user_role))

    def test_user_role_is_expired_false_without_expiry(self):
        user_role = UserRole.objects.create(
            user=self.user,
            role=self.role,
        )

        self.assertFalse(user_role.is_expired)

    def test_user_role_is_expired_true_after_expiry(self):
        user_role = UserRole.objects.create(
            user=self.user,
            role=self.role,
            expires_at=timezone.now() - timezone.timedelta(minutes=1),
        )

        self.assertTrue(user_role.is_expired)

    def test_admin_log_str_data_exists(self):
        log = AdminLog.objects.create(
            admin=self.admin,
            action="assign_role",
            target_user=self.user,
            target_role=self.role,
            details={"role_name": self.role.name},
        )

        self.assertEqual(log.action, "assign_role")
        self.assertEqual(log.target_user, self.user)
        self.assertEqual(log.target_role, self.role)


class RBACUtilsTestCase(RBACTestMixin, TestCase):
    def test_assign_role_creates_user_role(self):
        user_role = assign_role(
            user=self.user,
            role=self.role,
            assigned_by=self.admin,
        )

        self.assertEqual(user_role.user, self.user)
        self.assertEqual(user_role.role, self.role)
        self.assertEqual(user_role.assigned_by, self.admin)
        self.assertTrue(user_role.is_active)

    def test_assign_role_reactivates_existing_role(self):
        user_role = UserRole.objects.create(
            user=self.user,
            role=self.role,
            assigned_by=self.admin,
            is_active=False,
        )

        updated = assign_role(
            user=self.user,
            role=self.role,
            assigned_by=self.admin,
        )

        user_role.refresh_from_db()

        self.assertEqual(updated.id, user_role.id)
        self.assertTrue(user_role.is_active)

    def test_remove_role_deletes_user_role(self):
        assign_role(self.user, self.role, self.admin)

        remove_role(self.user, self.role)

        self.assertFalse(
            UserRole.objects.filter(
                user=self.user,
                role=self.role,
            ).exists()
        )

    def test_get_user_roles_ignores_expired_roles(self):
        active_role = assign_role(self.user, self.role, self.admin)
        expired_role = UserRole.objects.create(
            user=self.user,
            role=self.vendor_role,
            assigned_by=self.admin,
            expires_at=timezone.now() - timezone.timedelta(minutes=1),
        )

        roles = get_user_roles(self.user)

        self.assertIn(active_role, roles)
        self.assertNotIn(expired_role, roles)

    def test_get_user_permissions_returns_assigned_permissions(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )
        assign_role(self.user, self.role, self.admin)

        permissions = get_user_permissions(self.user)

        self.assertIn("view_products", permissions)

    def test_get_user_permissions_ignores_expired_roles(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )
        assign_role(
            user=self.user,
            role=self.role,
            assigned_by=self.admin,
            expires_at=timezone.now() - timezone.timedelta(minutes=1),
        )

        permissions = get_user_permissions(self.user)

        self.assertNotIn("view_products", permissions)

    def test_get_user_permissions_returns_empty_for_anonymous_user(self):
        anonymous = AnonymousUser()

        self.assertEqual(get_user_permissions(anonymous), [])

    def test_superuser_has_all_permissions(self):
        Permission.objects.create(
            name="Delete Products",
            codename="delete_products",
            module="products",
        )

        permissions = get_user_permissions(self.admin)

        self.assertIn("view_products", permissions)
        self.assertIn("delete_products", permissions)

    def test_has_permission_true_when_permission_exists(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )
        assign_role(self.user, self.role, self.admin)

        self.assertTrue(has_permission(self.user, "view_products"))

    def test_has_permission_false_when_permission_missing(self):
        assign_role(self.user, self.role, self.admin)

        self.assertFalse(has_permission(self.user, "missing_permission"))

    def test_clear_user_permissions_cache(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )
        assign_role(self.user, self.role, self.admin)

        self.assertIn("view_products", get_user_permissions(self.user))

        RolePermission.objects.filter(
            role=self.role,
            permission=self.permission,
        ).delete()

        self.assertIn("view_products", get_user_permissions(self.user))

        clear_user_permissions_cache(self.user)

        self.assertNotIn("view_products", get_user_permissions(self.user))

    def test_clear_role_permissions_cache(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )
        assign_role(self.user, self.role, self.admin)

        self.assertIn("view_products", get_user_permissions(self.user))

        RolePermission.objects.filter(
            role=self.role,
            permission=self.permission,
        ).delete()

        clear_role_permissions_cache(self.role)

        self.assertNotIn("view_products", get_user_permissions(self.user))

    def test_log_admin_action_creates_log(self):
        factory = RequestFactory()
        request = factory.post(
            "/api/rbac/assign-role/",
            HTTP_USER_AGENT="pytest-agent",
            REMOTE_ADDR="127.0.0.1",
        )

        log = log_admin_action(
            admin=self.admin,
            action="assign_role",
            target_user=self.user,
            target_role=self.role,
            details={"role_name": self.role.name},
            request=request,
        )

        self.assertEqual(log.admin, self.admin)
        self.assertEqual(log.action, "assign_role")
        self.assertEqual(log.ip_address, "127.0.0.1")
        self.assertEqual(log.user_agent, "pytest-agent")

    def test_get_client_ip_uses_forwarded_for(self):
        factory = RequestFactory()
        request = factory.get(
            "/",
            HTTP_X_FORWARDED_FOR="10.0.0.1, 10.0.0.2",
            REMOTE_ADDR="127.0.0.1",
        )

        self.assertEqual(get_client_ip(request), "10.0.0.1")


class RBACSerializerTestCase(RBACTestMixin, TestCase):
    def test_assign_role_serializer_valid(self):
        serializer = AssignRoleSerializer(
            data={
                "user_id": self.user.id,
                "role_id": self.role.id,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_assign_role_serializer_rejects_missing_user(self):
        serializer = AssignRoleSerializer(
            data={
                "user_id": 999999,
                "role_id": self.role.id,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("user_id", serializer.errors)

    def test_assign_role_serializer_rejects_missing_role(self):
        serializer = AssignRoleSerializer(
            data={
                "user_id": self.user.id,
                "role_id": 999999,
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("role_id", serializer.errors)

    def test_bulk_assign_serializer_validates_and_deduplicates_ids(self):
        serializer = BulkAssignRoleSerializer(
            data={
                "user_ids": [
                    self.user.id,
                    self.user.id,
                    self.second_user.id,
                ],
                "role_ids": [
                    self.role.id,
                    self.role.id,
                    self.vendor_role.id,
                ],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["user_ids"],
            [
                self.user.id,
                self.second_user.id,
            ],
        )
        self.assertEqual(
            serializer.validated_data["role_ids"],
            [
                self.role.id,
                self.vendor_role.id,
            ],
        )

    def test_bulk_assign_serializer_rejects_missing_users(self):
        serializer = BulkAssignRoleSerializer(
            data={
                "user_ids": [
                    self.user.id,
                    999999,
                ],
                "role_ids": [
                    self.role.id,
                ],
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("user_ids", serializer.errors)

    def test_bulk_assign_serializer_rejects_missing_roles(self):
        serializer = BulkAssignRoleSerializer(
            data={
                "user_ids": [
                    self.user.id,
                ],
                "role_ids": [
                    self.role.id,
                    999999,
                ],
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("role_ids", serializer.errors)


class RBACPermissionClassesTestCase(RBACTestMixin, TestCase):
    def make_request(self, user):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        return request

    def test_is_super_admin(self):
        permission = IsSuperAdmin()

        self.assertTrue(permission.has_permission(self.make_request(self.admin), None))
        self.assertFalse(permission.has_permission(self.make_request(self.user), None))

    def test_has_permission_class(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )
        assign_role(self.user, self.role, self.admin)

        permission = HasPermission("view_products")

        self.assertTrue(permission.has_permission(self.make_request(self.user), None))

    def test_has_any_permission_class(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )
        assign_role(self.user, self.role, self.admin)

        permission = HasAnyPermission("missing_permission", "view_products")

        self.assertTrue(permission.has_permission(self.make_request(self.user), None))

    def test_vendor_manager_permission_class(self):
        assign_role(self.user, self.vendor_role, self.admin)

        permission = IsVendorManager()

        self.assertTrue(permission.has_permission(self.make_request(self.user), None))

    def test_product_admin_permission_class(self):
        assign_role(self.user, self.product_role, self.admin)

        permission = IsProductAdmin()

        self.assertTrue(permission.has_permission(self.make_request(self.user), None))

    def test_content_admin_permission_class(self):
        assign_role(self.user, self.content_role, self.admin)

        permission = IsContentAdmin()

        self.assertTrue(permission.has_permission(self.make_request(self.user), None))

    def test_customer_permission_class(self):
        permission = IsCustomer()

        self.assertTrue(permission.has_permission(self.make_request(self.user), None))
        self.assertFalse(permission.has_permission(self.make_request(self.admin), None))


class RBACAPITestCase(RBACTestMixin, APITestCase):
    def get_response_items(self, response):
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]

        return response.data
    
    def test_non_admin_cannot_access_roles(self):
        self.authenticate(self.user)

        response = self.client.get("/api/rbac/roles/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_can_list_roles(self):
        self.authenticate(self.admin)

        response = self.client.get("/api/rbac/roles/")
        items = self.get_response_items(response)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(items), 1)

    def test_super_admin_can_filter_roles_by_name(self):
        self.authenticate(self.admin)

        response = self.client.get("/api/rbac/roles/?name=manager")
        items = self.get_response_items(response)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(role["name"] == "manager" for role in items)
        )

    def test_super_admin_can_create_role(self):
        self.authenticate(self.admin)

        response = self.client.post(
            "/api/rbac/roles/",
            {
                "name": "support_admin",
                "description": "Support admin role",
                "level": 50,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Role.objects.filter(name="support_admin").exists())

    def test_system_role_name_cannot_be_changed(self):
        self.authenticate(self.admin)

        response = self.client.patch(
            f"/api/rbac/roles/{self.system_role.id}/",
            {
                "name": "changed_customer",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.system_role.refresh_from_db()

        self.assertEqual(self.system_role.name, "customer")

    def test_system_role_cannot_be_deleted(self):
        self.authenticate(self.admin)

        response = self.client.delete(f"/api/rbac/roles/{self.system_role.id}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Role.objects.filter(id=self.system_role.id).exists())

    def test_non_system_role_can_be_deleted(self):
        role = Role.objects.create(
            name="temporary_role",
            description="Temporary role",
            level=99,
        )

        self.authenticate(self.admin)

        response = self.client.delete(f"/api/rbac/roles/{role.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Role.objects.filter(id=role.id).exists())

    def test_super_admin_can_list_permissions(self):
        self.authenticate(self.admin)

        response = self.client.get("/api/rbac/permissions/")
        items = self.get_response_items(response)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(items), 1)

    def test_super_admin_can_filter_permissions_by_module(self):
        self.authenticate(self.admin)

        response = self.client.get("/api/rbac/permissions/?module=products")
        items = self.get_response_items(response)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            all(permission["module"] == "products" for permission in items)
        )

    def test_super_admin_can_create_permission(self):
        self.authenticate(self.admin)

        response = self.client.post(
            "/api/rbac/permissions/",
            {
                "name": "Create Product",
                "codename": "create_product",
                "module": "products",
                "description": "Can create product",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Permission.objects.filter(codename="create_product").exists()
        )

    def test_role_permissions_action_lists_permissions(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )

        self.authenticate(self.admin)

        response = self.client.get(f"/api/rbac/roles/{self.role.id}/permissions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["permission_codename"], "view_products")

    def test_add_permission_to_role(self):
        self.authenticate(self.admin)

        response = self.client.post(
            f"/api/rbac/roles/{self.role.id}/add_permission/",
            {
                "permission_id": self.permission.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            RolePermission.objects.filter(
                role=self.role,
                permission=self.permission,
            ).exists()
        )

    def test_add_existing_permission_to_role_returns_200(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )

        self.authenticate(self.admin)

        response = self.client.post(
            f"/api/rbac/roles/{self.role.id}/add_permission/",
            {
                "permission_id": self.permission.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_add_missing_permission_to_role_returns_404(self):
        self.authenticate(self.admin)

        response = self.client.post(
            f"/api/rbac/roles/{self.role.id}/add_permission/",
            {
                "permission_id": 999999,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_remove_permission_from_role(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )

        self.authenticate(self.admin)

        response = self.client.delete(
            f"/api/rbac/roles/{self.role.id}/remove_permission/",
            {
                "permission_id": self.permission.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            RolePermission.objects.filter(
                role=self.role,
                permission=self.permission,
            ).exists()
        )

    def test_remove_missing_permission_from_role_returns_404(self):
        self.authenticate(self.admin)

        response = self.client.delete(
            f"/api/rbac/roles/{self.role.id}/remove_permission/",
            {
                "permission_id": 999999,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_assign_role_endpoint(self):
        self.authenticate(self.admin)

        response = self.client.post(
            "/api/rbac/assign-role/",
            {
                "user_id": self.user.id,
                "role_id": self.role.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            UserRole.objects.filter(
                user=self.user,
                role=self.role,
            ).exists()
        )
        self.assertTrue(
            AdminLog.objects.filter(
                admin=self.admin,
                action="assign_role",
                target_user=self.user,
                target_role=self.role,
            ).exists()
        )

    def test_assign_role_endpoint_rejects_missing_user(self):
        self.authenticate(self.admin)

        response = self.client.post(
            "/api/rbac/assign-role/",
            {
                "user_id": 999999,
                "role_id": self.role.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_role_endpoint(self):
        assign_role(self.user, self.role, self.admin)

        self.authenticate(self.admin)

        response = self.client.delete(
            f"/api/rbac/remove-role/{self.user.id}/{self.role.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            UserRole.objects.filter(
                user=self.user,
                role=self.role,
            ).exists()
        )
        self.assertTrue(
            AdminLog.objects.filter(
                admin=self.admin,
                action="remove_role",
                target_user=self.user,
                target_role=self.role,
            ).exists()
        )

    def test_remove_role_endpoint_returns_404_for_missing_data(self):
        self.authenticate(self.admin)

        response = self.client.delete(
            f"/api/rbac/remove-role/999999/{self.role.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_permissions_endpoint(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )
        assign_role(self.user, self.role, self.admin)

        self.authenticate(self.admin)

        response = self.client.get(f"/api/rbac/user-permissions/{self.user.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["user_email"], self.user.email)
        self.assertIn("view_products", response.data["permissions"])

    def test_user_permissions_endpoint_returns_404_for_missing_user(self):
        self.authenticate(self.admin)

        response = self.client.get("/api/rbac/user-permissions/999999/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_my_permissions_requires_authentication(self):
        response = self.client.get("/api/rbac/my-permissions/")

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_my_permissions_endpoint(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )
        assign_role(self.user, self.role, self.admin)

        self.authenticate(self.user)

        response = self.client.get("/api/rbac/my-permissions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.user.email)
        self.assertIn("view_products", response.data["permissions"])

    def test_check_permission_endpoint_true(self):
        RolePermission.objects.create(
            role=self.role,
            permission=self.permission,
        )
        assign_role(self.user, self.role, self.admin)

        self.authenticate(self.admin)

        response = self.client.post(
            "/api/rbac/check-permission/",
            {
                "user_id": self.user.id,
                "permission": "view_products",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["has_permission"])

    def test_check_permission_endpoint_false(self):
        assign_role(self.user, self.role, self.admin)

        self.authenticate(self.admin)

        response = self.client.post(
            "/api/rbac/check-permission/",
            {
                "user_id": self.user.id,
                "permission": "missing_permission",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["has_permission"])

    def test_user_roles_endpoint_lists_assignments(self):
        assign_role(self.user, self.role, self.admin)

        self.authenticate(self.admin)

        response = self.client.get("/api/rbac/user-roles/")
        items = self.get_response_items(response)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(
                user_role["user_email"] == self.user.email
                for user_role in items
            )
        )

    def test_user_roles_endpoint_filters_by_user_id(self):
        assign_role(self.user, self.role, self.admin)
        assign_role(self.second_user, self.vendor_role, self.admin)

        self.authenticate(self.admin)

        response = self.client.get(f"/api/rbac/user-roles/?user_id={self.user.id}")
        items = self.get_response_items(response)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            all(user_role["user"] == self.user.id for user_role in items)
        )

    def test_admin_logs_endpoint_lists_logs(self):
        log_admin_action(
            admin=self.admin,
            action="assign_role",
            target_user=self.user,
            target_role=self.role,
            details={"role_name": self.role.name},
        )

        self.authenticate(self.admin)

        response = self.client.get("/api/rbac/admin-logs/")
        items = self.get_response_items(response)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(items), 1)

    def test_admin_logs_endpoint_filters_by_action(self):
        log_admin_action(
            admin=self.admin,
            action="assign_role",
            target_user=self.user,
            target_role=self.role,
        )
        log_admin_action(
            admin=self.admin,
            action="remove_role",
            target_user=self.user,
            target_role=self.role,
        )

        self.authenticate(self.admin)

        response = self.client.get("/api/rbac/admin-logs/?action=assign_role")
        items = self.get_response_items(response)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            all(log["action"] == "assign_role" for log in items)
        )

    def test_admin_log_detail_endpoint(self):
        log = log_admin_action(
            admin=self.admin,
            action="assign_role",
            target_user=self.user,
            target_role=self.role,
        )

        self.authenticate(self.admin)

        response = self.client.get(f"/api/rbac/admin-logs/{log.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], log.id)

    def test_bulk_assign_roles_endpoint(self):
        self.authenticate(self.admin)

        response = self.client.post(
            "/api/rbac/bulk-assign/",
            {
                "user_ids": [
                    self.user.id,
                    self.second_user.id,
                ],
                "role_ids": [
                    self.role.id,
                    self.vendor_role.id,
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["summary"]["total_assignments"], 4)
        self.assertEqual(UserRole.objects.count(), 4)
        self.assertEqual(
            AdminLog.objects.filter(action="assign_role").count(),
            4,
        )

    def test_bulk_assign_roles_endpoint_rejects_missing_user(self):
        self.authenticate(self.admin)

        response = self.client.post(
            "/api/rbac/bulk-assign/",
            {
                "user_ids": [
                    self.user.id,
                    999999,
                ],
                "role_ids": [
                    self.role.id,
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_assign_roles_endpoint_rejects_missing_role(self):
        self.authenticate(self.admin)

        response = self.client.post(
            "/api/rbac/bulk-assign/",
            {
                "user_ids": [
                    self.user.id,
                ],
                "role_ids": [
                    self.role.id,
                    999999,
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)