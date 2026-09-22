from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from apps.rbac.models import (
    Permission,
    Role,
    RolePermission,
    UserRole,
)

User = get_user_model()


class InventoryPermissionTests(APITestCase):
    def setUp(self):
        cache.clear()

        self.superuser = self.create_user(
            email="inventory-superuser@example.com",
            full_name="Inventory Superuser",
            is_staff=True,
            is_superuser=True,
        )

        self.inventory_manager = self.create_user(
            email="inventory-manager@example.com",
            full_name="Inventory Manager",
            is_staff=True,
        )

        self.product_admin = self.create_user(
            email="product-admin@example.com",
            full_name="Product Admin",
            is_staff=True,
        )

        self.viewer = self.create_user(
            email="inventory-viewer@example.com",
            full_name="Inventory Viewer",
            is_staff=True,
        )

        self.inventory_editor = self.create_user(
            email="inventory-editor@example.com",
            full_name="Inventory Editor",
            is_staff=True,
        )

        # Created by rbac.0004_inventory_rbac migration.
        self.inventory_role = Role.objects.get(
            name="inventory_manager",
        )

        self.view_inventory_permission = Permission.objects.get(
            codename="view_inventory",
        )

        self.manage_inventory_permission = Permission.objects.get(
            codename="manage_inventory",
        )

        self.create_transfers_permission = Permission.objects.get(
            codename="create_stock_transfers",
        )

        # Test-only roles.
        self.product_admin_role = Role.objects.create(
            name="product_admin",
            description="Product admin role",
            level=70,
            is_system_role=True,
        )

        self.viewer_role = Role.objects.create(
            name="inventory_viewer",
            description="Inventory read-only role",
            level=60,
        )

        self.editor_role = Role.objects.create(
            name="inventory_editor",
            description=("Inventory editor without transfer management"),
            level=60,
        )

        self.assign_permission(
            self.viewer_role,
            self.view_inventory_permission,
        )

        self.assign_permission(
            self.editor_role,
            self.view_inventory_permission,
        )

        self.assign_permission(
            self.editor_role,
            self.manage_inventory_permission,
        )

        self.assign_role(
            self.inventory_manager,
            self.inventory_role,
        )

        self.assign_role(
            self.product_admin,
            self.product_admin_role,
        )

        self.assign_role(
            self.viewer,
            self.viewer_role,
        )

        self.assign_role(
            self.inventory_editor,
            self.editor_role,
        )

    def tearDown(self):
        cache.clear()

    def create_user(
        self,
        *,
        email,
        full_name,
        is_staff=False,
        is_superuser=False,
    ):
        user = User(
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        user.set_password("StrongPass123!")
        user.save()

        return user

    def assign_permission(
        self,
        role,
        permission,
    ):
        RolePermission.objects.create(
            role=role,
            permission=permission,
        )

    def assign_role(
        self,
        user,
        role,
    ):
        UserRole.objects.create(
            user=user,
            role=role,
            assigned_by=self.superuser,
            is_active=True,
        )

    def authenticate(self, user):
        cache.clear()

        self.client.force_authenticate(
            user=user,
        )

    def test_inventory_role_has_expected_permissions(self):
        permission_codenames = set(
            self.inventory_role.role_permissions.values_list(
                "permission__codename",
                flat=True,
            )
        )

        self.assertTrue(
            {
                "view_inventory",
                "manage_inventory",
                "create_stock_transfers",
            }.issubset(permission_codenames)
        )

        # The old broad transfer permission must not be assigned.
        self.assertNotIn(
            "manage_stock_transfers",
            permission_codenames,
        )

    def test_superuser_can_view_inventory(self):
        self.authenticate(
            self.superuser,
        )

        response = self.client.get(
            "/api/inventory/stocks/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_inventory_manager_can_view_inventory(self):
        self.authenticate(
            self.inventory_manager,
        )

        response = self.client.get(
            "/api/inventory/stocks/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_inventory_manager_can_access_inventory_write_endpoint(
        self,
    ):
        self.authenticate(
            self.inventory_manager,
        )

        response = self.client.post(
            "/api/inventory/stocks/",
            {},
            format="json",
        )

        # Permission passed.
        # Serializer rejects the empty request body.
        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_product_admin_without_inventory_permissions_is_denied(
        self,
    ):
        self.authenticate(
            self.product_admin,
        )

        response = self.client.get(
            "/api/inventory/stocks/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_inventory_viewer_can_read_inventory(self):
        self.authenticate(
            self.viewer,
        )

        response = self.client.get(
            "/api/inventory/stocks/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_inventory_viewer_cannot_modify_inventory(self):
        self.authenticate(
            self.viewer,
        )

        response = self.client.post(
            "/api/inventory/stocks/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_inventory_manager_can_access_transfer_write_endpoint(
        self,
    ):
        self.authenticate(
            self.inventory_manager,
        )

        response = self.client.post(
            "/api/inventory/stock-transfers/",
            {},
            format="json",
        )

        # Permission passed.
        # Serializer rejects the empty request body.
        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_inventory_editor_without_transfer_permission_is_denied(
        self,
    ):
        self.authenticate(
            self.inventory_editor,
        )

        response = self.client.post(
            "/api/inventory/stock-transfers/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_unauthenticated_user_cannot_view_inventory(self):
        response = self.client.get(
            "/api/inventory/stocks/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


def test_supervisor_can_view_but_cannot_modify_inventory(self):
    supervisor = self.create_user(
        email="readonly-supervisor@example.com",
        full_name="Read-only Supervisor",
        is_staff=True,
    )

    role = Role.objects.get(
        name="inventory_supervisor",
    )

    self.assign_role(supervisor, role)
    self.authenticate(supervisor)

    response = self.client.get(
        "/api/inventory/stocks/",
    )
    self.assertEqual(
        response.status_code,
        status.HTTP_200_OK,
    )

    response = self.client.post(
        "/api/inventory/stocks/",
        {},
        format="json",
    )
    self.assertEqual(
        response.status_code,
        status.HTTP_403_FORBIDDEN,
    )

    response = self.client.post(
        "/api/inventory/stock-movements/",
        {},
        format="json",
    )
    self.assertEqual(
        response.status_code,
        status.HTTP_403_FORBIDDEN,
    )
