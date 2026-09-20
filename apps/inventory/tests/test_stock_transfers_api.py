from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from apps.inventory.models import (
    Stock,
    StockMovement,
    StockTransfer,
    Warehouse,
)
from apps.products.models import Category, Product
from apps.rbac.models import Role, UserRole

User = get_user_model()


class StockTransferAPITests(APITestCase):
    def setUp(self):
        cache.clear()

        self.manager = User.objects.create_user(
            email="transfer-manager@example.com",
            phone="+989533333331",
            full_name="Transfer Manager",
            password="StrongPass123!",
            is_staff=True,
        )

        self.seller = User.objects.create_user(
            email="transfer-seller@example.com",
            phone="+989533333332",
            full_name="Transfer Seller",
            password="StrongPass123!",
            is_seller=True,
        )

        inventory_role = Role.objects.get(
            name="inventory_manager",
        )

        UserRole.objects.create(
            user=self.manager,
            role=inventory_role,
            assigned_by=self.manager,
            is_active=True,
        )

        cache.clear()

        self.category = Category.objects.create(
            name="Transfer Test Category",
            description="Category for stock transfer tests",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Transfer Test Keyboard",
            description="Product for transfer tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="TRANSFER-KEYBOARD-001",
        )

        self.main_warehouse = Warehouse.objects.create(
            name="Transfer Main Warehouse",
            code="TRANSFER-MAIN",
            type=Warehouse.TypeChoices.MAIN,
            province="Bavaria",
            city="Bamberg",
            address="Main warehouse test address",
            postal_code="96047",
            phone="+499511111101",
            email="transfer-main@example.com",
            manager_name="Main Manager",
            manager_phone="+491761111101",
            is_active=True,
            created_by=self.manager,
        )

        self.branch_warehouse = Warehouse.objects.create(
            name="Transfer Branch Warehouse",
            code="TRANSFER-BRANCH",
            type=Warehouse.TypeChoices.BRANCH,
            province="Bavaria",
            city="Bamberg",
            address="Branch warehouse test address",
            postal_code="96048",
            phone="+499511111102",
            email="transfer-branch@example.com",
            manager_name="Branch Manager",
            manager_phone="+491761111102",
            is_active=True,
            created_by=self.manager,
        )

        self.source_stock = Stock.objects.create(
            product=self.product,
            warehouse=self.main_warehouse,
            quantity=10,
            reserved_quantity=2,
            low_stock_threshold=2,
            updated_by=self.manager,
        )

        self.client.force_authenticate(
            user=self.manager,
        )

    def tearDown(self):
        cache.clear()

    def create_transfer(self, quantity=5):
        response = self.client.post(
            "/api/inventory/stock-transfers/",
            {
                "from_warehouse": self.main_warehouse.id,
                "to_warehouse": self.branch_warehouse.id,
                "product": self.product.id,
                "quantity": quantity,
                "reason": "Restock branch warehouse",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        return StockTransfer.objects.get(
            id=response.data["id"],
        )

    def test_create_transfer_starts_pending_without_changing_stock(
        self,
    ):
        transfer = self.create_transfer()

        self.source_stock.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.PENDING,
        )
        self.assertEqual(
            transfer.quantity,
            5,
        )

        self.assertEqual(
            self.source_stock.quantity,
            10,
        )

        self.assertFalse(
            Stock.objects.filter(
                product=self.product,
                warehouse=self.branch_warehouse,
            ).exists()
        )

        self.assertEqual(
            StockMovement.objects.count(),
            0,
        )

    def test_transfer_rejects_same_source_and_destination(
        self,
    ):
        response = self.client.post(
            "/api/inventory/stock-transfers/",
            {
                "from_warehouse": self.main_warehouse.id,
                "to_warehouse": self.main_warehouse.id,
                "product": self.product.id,
                "quantity": 2,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(
            StockTransfer.objects.count(),
            0,
        )

    def test_transfer_rejects_quantity_above_available_stock(
        self,
    ):
        # Total = 10
        # Reserved = 2
        # Available = 8
        response = self.client.post(
            "/api/inventory/stock-transfers/",
            {
                "from_warehouse": self.main_warehouse.id,
                "to_warehouse": self.branch_warehouse.id,
                "product": self.product.id,
                "quantity": 9,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertEqual(
            StockTransfer.objects.count(),
            0,
        )

        self.source_stock.refresh_from_db()

        self.assertEqual(
            self.source_stock.quantity,
            10,
        )

    def test_mark_in_transit_does_not_change_inventory(
        self,
    ):
        transfer = self.create_transfer()

        response = self.client.post(
            (f"/api/inventory/stock-transfers/" f"{transfer.id}/mark-in-transit/"),
            {
                "tracking_number": "TR-2026-001",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        transfer.refresh_from_db()
        self.source_stock.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.IN_TRANSIT,
        )
        self.assertEqual(
            transfer.tracking_number,
            "TR-2026-001",
        )
        self.assertIsNotNone(
            transfer.shipped_at,
        )

        self.assertEqual(
            self.source_stock.quantity,
            10,
        )

        self.assertEqual(
            StockMovement.objects.count(),
            0,
        )

    def test_pending_transfer_cannot_be_completed_directly(
        self,
    ):
        transfer = self.create_transfer()

        response = self.client.post(
            (f"/api/inventory/stock-transfers/" f"{transfer.id}/complete/"),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        transfer.refresh_from_db()
        self.source_stock.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.PENDING,
        )

        self.assertEqual(
            self.source_stock.quantity,
            10,
        )

        self.assertEqual(
            StockMovement.objects.count(),
            0,
        )

    def test_complete_transfer_moves_stock_between_warehouses(
        self,
    ):
        transfer = self.create_transfer(
            quantity=5,
        )

        self.client.post(
            (f"/api/inventory/stock-transfers/" f"{transfer.id}/mark-in-transit/"),
            {
                "tracking_number": "TR-2026-002",
            },
            format="json",
        )

        response = self.client.post(
            (f"/api/inventory/stock-transfers/" f"{transfer.id}/complete/"),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        transfer.refresh_from_db()
        self.source_stock.refresh_from_db()

        destination_stock = Stock.objects.get(
            product=self.product,
            warehouse=self.branch_warehouse,
        )

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.COMPLETED,
        )

        self.assertIsNotNone(
            transfer.delivered_at,
        )

        self.assertEqual(
            self.source_stock.quantity,
            5,
        )

        self.assertEqual(
            self.source_stock.reserved_quantity,
            2,
        )

        self.assertEqual(
            destination_stock.quantity,
            5,
        )

        # Total inventory must remain unchanged.
        self.assertEqual(
            self.source_stock.quantity + destination_stock.quantity,
            10,
        )

    def test_complete_transfer_creates_two_audit_movements(
        self,
    ):
        transfer = self.create_transfer(
            quantity=5,
        )

        self.client.post(
            (f"/api/inventory/stock-transfers/" f"{transfer.id}/mark-in-transit/"),
            {},
            format="json",
        )

        self.client.post(
            (f"/api/inventory/stock-transfers/" f"{transfer.id}/complete/"),
            {},
            format="json",
        )

        movements = StockMovement.objects.filter(
            reference_id=f"transfer:{transfer.id}",
        )

        self.assertEqual(
            movements.count(),
            2,
        )

        transfer_out = movements.get(
            movement_type=StockMovement.MovementType.TRANSFER_OUT,
        )

        transfer_in = movements.get(
            movement_type=StockMovement.MovementType.TRANSFER_IN,
        )

        self.assertEqual(
            transfer_out.quantity,
            -5,
        )
        self.assertEqual(
            transfer_out.before_quantity,
            10,
        )
        self.assertEqual(
            transfer_out.after_quantity,
            5,
        )
        self.assertEqual(
            transfer_out.warehouse,
            self.main_warehouse,
        )

        self.assertEqual(
            transfer_in.quantity,
            5,
        )
        self.assertEqual(
            transfer_in.before_quantity,
            0,
        )
        self.assertEqual(
            transfer_in.after_quantity,
            5,
        )
        self.assertEqual(
            transfer_in.warehouse,
            self.branch_warehouse,
        )

    def test_cancel_pending_transfer_does_not_change_inventory(
        self,
    ):
        transfer = self.create_transfer(
            quantity=2,
        )

        response = self.client.post(
            (f"/api/inventory/stock-transfers/" f"{transfer.id}/cancel/"),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        transfer.refresh_from_db()
        self.source_stock.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.CANCELLED,
        )

        self.assertEqual(
            self.source_stock.quantity,
            10,
        )

        self.assertFalse(
            Stock.objects.filter(
                product=self.product,
                warehouse=self.branch_warehouse,
            ).exists()
        )

        self.assertEqual(
            StockMovement.objects.count(),
            0,
        )

    def test_transfer_cannot_be_updated_directly(
        self,
    ):
        transfer = self.create_transfer()

        response = self.client.patch(
            (f"/api/inventory/stock-transfers/" f"{transfer.id}/"),
            {
                "quantity": 1,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_transfer_cannot_be_deleted_directly(
        self,
    ):
        transfer = self.create_transfer()

        response = self.client.delete(
            (f"/api/inventory/stock-transfers/" f"{transfer.id}/"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        self.assertTrue(
            StockTransfer.objects.filter(
                id=transfer.id,
            ).exists()
        )
