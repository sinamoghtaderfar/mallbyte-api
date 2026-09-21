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

        self.supervisor = User.objects.create_user(
            email="transfer-supervisor@example.com",
            phone="+989533333332",
            full_name="Inventory Supervisor",
            password="StrongPass123!",
            is_staff=True,
        )

        self.seller = User.objects.create_user(
            email="transfer-seller@example.com",
            phone="+989533333333",
            full_name="Transfer Seller",
            password="StrongPass123!",
            is_seller=True,
        )

        inventory_manager_role = Role.objects.get(
            name="inventory_manager",
        )
        inventory_supervisor_role = Role.objects.get(
            name="inventory_supervisor",
        )

        UserRole.objects.create(
            user=self.manager,
            role=inventory_manager_role,
            assigned_by=self.supervisor,
            is_active=True,
        )

        UserRole.objects.create(
            user=self.supervisor,
            role=inventory_supervisor_role,
            assigned_by=self.supervisor,
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
            created_by=self.supervisor,
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
            created_by=self.supervisor,
        )

        self.source_stock = Stock.objects.create(
            product=self.product,
            warehouse=self.main_warehouse,
            quantity=10,
            reserved_quantity=2,
            low_stock_threshold=2,
            updated_by=self.manager,
        )

        self.authenticate(self.manager)

    def tearDown(self):
        cache.clear()

    def authenticate(self, user):
        cache.clear()
        self.client.force_authenticate(user=user)

    def create_transfer(self, quantity=5, user=None):
        if user is not None:
            self.authenticate(user)

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

    def approve_transfer(self, transfer):
        self.authenticate(self.supervisor)

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        transfer.refresh_from_db()
        return transfer

    def ship_transfer(self, transfer, tracking_number="TR-2026-001"):
        self.authenticate(self.manager)

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/mark-in-transit/",
            {
                "tracking_number": tracking_number,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        transfer.refresh_from_db()
        return transfer

    def test_create_transfer_starts_pending_without_changing_stock(self):
        transfer = self.create_transfer()

        self.source_stock.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.PENDING,
        )
        self.assertEqual(
            transfer.requested_by,
            self.manager,
        )
        self.assertIsNone(
            transfer.approved_by,
        )
        self.assertIsNone(
            transfer.approved_at,
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

    def test_transfer_rejects_same_source_and_destination(self):
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

    def test_transfer_rejects_quantity_above_available_stock(self):
        # Total = 10, Reserved = 2, Available = 8.
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

    def test_inventory_manager_without_approval_permission_cannot_approve(self):
        transfer = self.create_transfer()

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        transfer.refresh_from_db()
        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.PENDING,
        )
        self.assertIsNone(
            transfer.approved_by,
        )

    def test_requester_cannot_approve_own_transfer_even_with_approval_permission(self):
        transfer = self.create_transfer(
            user=self.supervisor,
        )

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/approve/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        transfer.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.PENDING,
        )
        self.assertIsNone(
            transfer.approved_by,
        )
        self.assertIsNone(
            transfer.approved_at,
        )

    def test_supervisor_can_approve_another_users_transfer(self):
        transfer = self.create_transfer()

        self.approve_transfer(transfer)

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.APPROVED,
        )
        self.assertEqual(
            transfer.approved_by,
            self.supervisor,
        )
        self.assertIsNotNone(
            transfer.approved_at,
        )

        self.source_stock.refresh_from_db()

        # Approval alone must not move inventory.
        self.assertEqual(
            self.source_stock.quantity,
            10,
        )
        self.assertEqual(
            StockMovement.objects.count(),
            0,
        )

    def test_pending_transfer_cannot_be_marked_in_transit(self):
        transfer = self.create_transfer()

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/mark-in-transit/",
            {
                "tracking_number": "TR-2026-001",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        transfer.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.PENDING,
        )
        self.assertIsNone(
            transfer.shipped_at,
        )

    def test_approved_transfer_can_be_marked_in_transit_without_changing_inventory(
        self,
    ):
        transfer = self.create_transfer()
        self.approve_transfer(transfer)

        original_approver_id = transfer.approved_by_id

        self.ship_transfer(
            transfer,
            tracking_number="TR-2026-002",
        )

        self.source_stock.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.IN_TRANSIT,
        )
        self.assertEqual(
            transfer.tracking_number,
            "TR-2026-002",
        )
        self.assertIsNotNone(
            transfer.shipped_at,
        )

        # Shipping must not overwrite the approver.
        self.assertEqual(
            transfer.approved_by_id,
            original_approver_id,
        )

        self.assertEqual(
            self.source_stock.quantity,
            10,
        )
        self.assertEqual(
            StockMovement.objects.count(),
            0,
        )

    def test_pending_transfer_cannot_be_completed_directly(self):
        transfer = self.create_transfer()

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/complete/",
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

    def test_complete_transfer_moves_stock_and_preserves_approver(self):
        transfer = self.create_transfer(
            quantity=5,
        )

        self.approve_transfer(transfer)
        approver_id = transfer.approved_by_id
        approved_at = transfer.approved_at

        self.ship_transfer(
            transfer,
            tracking_number="TR-2026-003",
        )

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/complete/",
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

        # Complete must not overwrite approval audit fields.
        self.assertEqual(
            transfer.approved_by_id,
            approver_id,
        )
        self.assertEqual(
            transfer.approved_at,
            approved_at,
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

        # Transfer changes location, not total inventory.
        self.assertEqual(
            self.source_stock.quantity + destination_stock.quantity,
            10,
        )

    def test_complete_transfer_creates_two_audit_movements(self):
        transfer = self.create_transfer(
            quantity=5,
        )

        self.approve_transfer(transfer)
        self.ship_transfer(transfer)

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/complete/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
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

    def test_requester_cannot_cancel_own_transfer_without_approval_permission(self):
        transfer = self.create_transfer(
            quantity=2,
        )

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/cancel/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        transfer.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.PENDING,
        )

    def test_requester_cannot_cancel_own_transfer_even_with_approval_permission(self):
        transfer = self.create_transfer(
            quantity=2,
            user=self.supervisor,
        )

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/cancel/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        transfer.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.PENDING,
        )

    def test_supervisor_can_cancel_another_users_pending_transfer_without_stock_change(
        self,
    ):
        transfer = self.create_transfer(
            quantity=2,
        )

        self.authenticate(self.supervisor)

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/cancel/",
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

    def test_in_transit_transfer_cannot_be_cancelled(self):
        transfer = self.create_transfer(
            quantity=2,
        )

        self.approve_transfer(transfer)
        self.ship_transfer(transfer)

        self.authenticate(self.supervisor)

        response = self.client.post(
            f"/api/inventory/stock-transfers/{transfer.id}/cancel/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        transfer.refresh_from_db()

        self.assertEqual(
            transfer.status,
            StockTransfer.StatusChoices.IN_TRANSIT,
        )

    def test_transfer_cannot_be_updated_directly(self):
        transfer = self.create_transfer()

        response = self.client.patch(
            f"/api/inventory/stock-transfers/{transfer.id}/",
            {
                "quantity": 1,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_transfer_cannot_be_deleted_directly(self):
        transfer = self.create_transfer()

        response = self.client.delete(
            f"/api/inventory/stock-transfers/{transfer.id}/",
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
