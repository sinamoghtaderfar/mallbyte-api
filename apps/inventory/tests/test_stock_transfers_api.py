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
    WarehouseMembership,
)
from apps.products.models import Category, Product
from apps.rbac.models import Role, UserRole

User = get_user_model()
BASE_URL = "/api/inventory/stock-transfers/"


class StockTransferAPITests(APITestCase):
    """One test database per test; all stock amounts are deliberate."""

    def setUp(self):
        cache.clear()
        self.manager = self.make_user("manager", 1)
        self.supervisor = self.make_user("supervisor", 2)
        self.source_operator = self.make_user("source-operator", 3)
        self.destination_operator = self.make_user("destination-operator", 4)
        self.seller = self.make_user("seller", 5, is_seller=True)

        for user, role_name in (
            (self.manager, "inventory_manager"),
            (self.supervisor, "inventory_supervisor"),
            (self.source_operator, "warehouse_operator"),
            (self.destination_operator, "warehouse_operator"),
        ):
            UserRole.objects.create(
                user=user,
                role=Role.objects.get(name=role_name),
                assigned_by=self.supervisor,
                is_active=True,
            )
        cache.clear()

        self.category = Category.objects.create(
            name="Stock Transfer Workflow Test",
            description="API transfer regression tests",
            is_active=True,
        )
        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Test Keyboard",
            description="Test warehouse transfer",
            price=Decimal("100000.00"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="TRANSFER-WORKFLOW-TEST",
        )

        self.source = self.make_warehouse("Main", "MAIN", self.manager)
        self.destination = self.make_warehouse("Branch", "BRANCH", self.manager)
        self.source_stock = Stock.objects.create(
            product=self.product,
            warehouse=self.source,
            quantity=10,
            reserved_quantity=2,
            low_stock_threshold=2,
            updated_by=self.manager,
        )
        self.source_membership = WarehouseMembership.objects.create(
            user=self.source_operator,
            warehouse=self.source,
            assigned_by=self.supervisor,
            is_active=True,
        )
        self.destination_membership = WarehouseMembership.objects.create(
            user=self.destination_operator,
            warehouse=self.destination,
            assigned_by=self.supervisor,
            is_active=True,
        )
        self.authenticate(self.manager)

    def tearDown(self):
        cache.clear()

    @staticmethod
    def make_user(label, index, *, is_seller=False):
        return User.objects.create_user(
            email=f"transfer-{label}@example.com",
            phone=f"+9895333333{index:02d}",
            full_name=label.replace("-", " ").title(),
            password="StrongPass123!",
            is_staff=not is_seller,
            is_seller=is_seller,
        )

    @staticmethod
    def make_warehouse(name, code, owner):
        return Warehouse.objects.create(
            name=f"Workflow {name}",
            code=f"WORKFLOW-{code}",
            type=(
                Warehouse.TypeChoices.MAIN
                if code == "MAIN"
                else Warehouse.TypeChoices.BRANCH
            ),
            province="Bavaria",
            city="Bamberg",
            address="Test warehouse address",
            postal_code="96047",
            phone="+499511111101",
            email=f"workflow-{code.lower()}@example.com",
            manager_name="Test Manager",
            manager_phone="+491761111101",
            is_active=True,
            created_by=owner,
        )

    def authenticate(self, user):
        cache.clear()
        self.client.force_authenticate(user=user)

    def endpoint(self, transfer, action):
        return f"{BASE_URL}{transfer.pk}/{action}/"

    def request_transfer(self, quantity=5, *, user=None):
        self.authenticate(self.manager if user is None else user)
        return self.client.post(
            BASE_URL,
            {
                "from_warehouse": self.source.pk,
                "to_warehouse": self.destination.pk,
                "product": self.product.pk,
                "quantity": quantity,
                "reason": "Replenish branch",
            },
            format="json",
        )

    def create_transfer(self, quantity=5):
        response = self.request_transfer(quantity)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return StockTransfer.objects.get(pk=response.data["id"])

    def approve_transfer(self, transfer):
        self.authenticate(self.supervisor)
        response = self.client.post(
            self.endpoint(transfer, "approve"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        transfer.refresh_from_db()
        return transfer

    def ship_transfer(self, transfer, *, user=None, tracking="TEST-TRACK-001"):
        self.authenticate(self.source_operator if user is None else user)
        response = self.client.post(
            self.endpoint(transfer, "ship"),
            {"tracking_number": tracking},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        transfer.refresh_from_db()
        return transfer

    def receive_transfer(self, transfer, *, user=None):
        self.authenticate(self.destination_operator if user is None else user)
        response = self.client.post(
            self.endpoint(transfer, "receive"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        transfer.refresh_from_db()
        return transfer

    def assert_no_movements(self):
        self.assertFalse(StockMovement.objects.exists())

    # Creation and approval

    def test_create_starts_pending_without_changing_any_stock(self):
        transfer = self.create_transfer()
        self.source_stock.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.StatusChoices.PENDING)
        self.assertEqual(transfer.requested_by, self.manager)
        self.assertIsNone(transfer.approved_at)
        self.assertEqual(self.source_stock.quantity, 10)
        self.assertFalse(
            Stock.objects.filter(
                product=self.product, warehouse=self.destination
            ).exists()
        )
        self.assert_no_movements()

    def test_rejects_same_source_and_destination(self):
        response = self.client.post(
            BASE_URL,
            {
                "from_warehouse": self.source.pk,
                "to_warehouse": self.source.pk,
                "product": self.product.pk,
                "quantity": 2,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(StockTransfer.objects.exists())

    def test_rejects_quantity_exceeding_unreserved_stock(self):
        response = self.request_transfer(quantity=9)  # 10 total - 2 reserved = 8.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(StockTransfer.objects.exists())
        self.source_stock.refresh_from_db()
        self.assertEqual(self.source_stock.quantity, 10)

    def test_supervisor_cannot_create_a_transfer(self):
        response = self.request_transfer(user=self.supervisor)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(StockTransfer.objects.exists())

    def test_warehouse_operator_cannot_create_a_transfer(self):
        response = self.request_transfer(user=self.source_operator)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_cannot_approve(self):
        transfer = self.create_transfer()
        response = self.client.post(
            self.endpoint(transfer, "approve"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.StatusChoices.PENDING)

    def test_requester_cannot_approve_own_transfer_even_if_supervisor(self):
        # Create directly to prove the model's Maker-Checker guard independently of API RBAC.
        transfer = StockTransfer.objects.create(
            from_warehouse=self.source,
            to_warehouse=self.destination,
            product=self.product,
            quantity=2,
            requested_by=self.supervisor,
        )
        self.authenticate(self.supervisor)
        response = self.client.post(
            self.endpoint(transfer, "approve"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.StatusChoices.PENDING)
        self.assertIsNone(transfer.approved_by)

    def test_supervisor_approves_another_users_request_without_moving_stock(self):
        transfer = self.create_transfer()
        self.approve_transfer(transfer)
        self.source_stock.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.StatusChoices.APPROVED)
        self.assertEqual(transfer.approved_by, self.supervisor)
        self.assertIsNotNone(transfer.approved_at)
        self.assertEqual(self.source_stock.quantity, 10)
        self.assert_no_movements()

    def test_warehouse_operator_cannot_approve(self):
        transfer = self.create_transfer()
        self.authenticate(self.source_operator)
        response = self.client.post(
            self.endpoint(transfer, "approve"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # Goods issue: Ship only from the assigned source warehouse.

    def test_cannot_ship_a_pending_transfer(self):
        transfer = self.create_transfer()
        self.authenticate(self.source_operator)
        response = self.client.post(self.endpoint(transfer, "ship"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_no_movements()

    def test_manager_cannot_ship_even_with_source_membership(self):
        transfer = self.approve_transfer(self.create_transfer())
        WarehouseMembership.objects.create(user=self.manager, warehouse=self.source)
        self.authenticate(self.manager)
        response = self.client.post(self.endpoint(transfer, "ship"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assert_no_movements()

    def test_supervisor_cannot_ship_even_with_source_membership(self):
        transfer = self.approve_transfer(self.create_transfer())
        WarehouseMembership.objects.create(user=self.supervisor, warehouse=self.source)
        self.authenticate(self.supervisor)
        response = self.client.post(self.endpoint(transfer, "ship"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assert_no_movements()

    def test_operator_cannot_ship_from_unassigned_source(self):
        transfer = self.approve_transfer(self.create_transfer())
        self.authenticate(self.destination_operator)
        response = self.client.post(self.endpoint(transfer, "ship"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_no_movements()

    def test_inactive_source_membership_cannot_ship(self):
        transfer = self.approve_transfer(self.create_transfer())
        self.source_membership.is_active = False
        self.source_membership.save(update_fields=["is_active"])
        self.authenticate(self.source_operator)
        response = self.client.post(self.endpoint(transfer, "ship"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_no_movements()

    def test_ship_debits_source_once_and_records_audit(self):
        transfer = self.approve_transfer(self.create_transfer(quantity=5))
        approver, approved_at = transfer.approved_by, transfer.approved_at
        self.ship_transfer(transfer, tracking="SHIP-42")
        self.source_stock.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.StatusChoices.IN_TRANSIT)
        self.assertEqual(transfer.shipped_by, self.source_operator)
        self.assertIsNotNone(transfer.shipped_at)
        self.assertEqual(transfer.tracking_number, "SHIP-42")
        self.assertEqual(
            (transfer.approved_by, transfer.approved_at), (approver, approved_at)
        )
        self.assertEqual(
            (self.source_stock.quantity, self.source_stock.reserved_quantity), (5, 2)
        )
        self.assertFalse(
            Stock.objects.filter(
                product=self.product, warehouse=self.destination
            ).exists()
        )
        self.assertEqual(StockMovement.objects.count(), 1)
        movement = StockMovement.objects.get(reference_id=f"transfer:{transfer.id}")
        self.assertEqual(
            movement.movement_type, StockMovement.MovementType.TRANSFER_OUT
        )
        self.assertEqual(
            (movement.quantity, movement.before_quantity, movement.after_quantity),
            (-5, 10, 5),
        )
        self.assertEqual(movement.warehouse, self.source)
        self.assertEqual(movement.created_by, self.source_operator)

    def test_double_ship_does_not_debit_twice(self):
        transfer = self.approve_transfer(self.create_transfer())
        self.ship_transfer(transfer)
        self.authenticate(self.source_operator)
        response = self.client.post(self.endpoint(transfer, "ship"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.source_stock.refresh_from_db()
        self.assertEqual(self.source_stock.quantity, 5)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_ship_rolls_back_when_stock_became_reserved_after_approval(self):
        transfer = self.approve_transfer(self.create_transfer(quantity=5))
        self.source_stock.reserved_quantity = 7  # Now only 3 available.
        self.source_stock.save(update_fields=["reserved_quantity"])
        self.authenticate(self.source_operator)
        response = self.client.post(self.endpoint(transfer, "ship"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        transfer.refresh_from_db()
        self.source_stock.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.StatusChoices.APPROVED)
        self.assertIsNone(transfer.shipped_at)
        self.assertEqual(
            (self.source_stock.quantity, self.source_stock.reserved_quantity), (10, 7)
        )
        self.assert_no_movements()

    # Goods receipt: Receive only at the assigned destination warehouse.

    def test_cannot_receive_pending_or_approved_transfer(self):
        transfer = self.create_transfer()
        self.authenticate(self.destination_operator)
        response = self.client.post(
            self.endpoint(transfer, "receive"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.approve_transfer(transfer)
        self.authenticate(self.destination_operator)
        response = self.client.post(
            self.endpoint(transfer, "receive"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_no_movements()

    def test_manager_and_supervisor_cannot_receive(self):
        transfer = self.approve_transfer(self.create_transfer())
        self.ship_transfer(transfer)
        for user in (self.manager, self.supervisor):
            with self.subTest(user=user.email):
                self.authenticate(user)
                response = self.client.post(
                    self.endpoint(transfer, "receive"), {}, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_source_operator_cannot_receive_at_unassigned_destination(self):
        transfer = self.approve_transfer(self.create_transfer())
        self.ship_transfer(transfer)
        self.authenticate(self.source_operator)
        response = self.client.post(
            self.endpoint(transfer, "receive"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.StatusChoices.IN_TRANSIT)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_inactive_destination_membership_cannot_receive(self):
        transfer = self.approve_transfer(self.create_transfer())
        self.ship_transfer(transfer)
        self.destination_membership.is_active = False
        self.destination_membership.save(update_fields=["is_active"])
        self.authenticate(self.destination_operator)
        response = self.client.post(
            self.endpoint(transfer, "receive"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_receive_credits_destination_once_and_preserves_all_audit_fields(self):
        transfer = self.approve_transfer(self.create_transfer(quantity=5))
        self.ship_transfer(transfer, tracking="TRACE-99")
        approver, approved_at = transfer.approved_by, transfer.approved_at
        shipped_by, shipped_at = transfer.shipped_by, transfer.shipped_at
        self.receive_transfer(transfer)
        self.source_stock.refresh_from_db()
        dest_stock = Stock.objects.get(product=self.product, warehouse=self.destination)
        self.assertEqual(transfer.status, StockTransfer.StatusChoices.COMPLETED)
        self.assertEqual(transfer.received_by, self.destination_operator)
        self.assertIsNotNone(transfer.received_at)
        self.assertEqual(
            (transfer.approved_by, transfer.approved_at), (approver, approved_at)
        )
        self.assertEqual(
            (transfer.shipped_by, transfer.shipped_at), (shipped_by, shipped_at)
        )
        self.assertEqual(
            (self.source_stock.quantity, self.source_stock.reserved_quantity), (5, 2)
        )
        self.assertEqual(dest_stock.quantity, 5)
        self.assertEqual(self.source_stock.quantity + dest_stock.quantity, 10)
        out = StockMovement.objects.get(
            reference_id=f"transfer:{transfer.pk}", movement_type="transfer_out"
        )
        inc = StockMovement.objects.get(
            reference_id=f"transfer:{transfer.pk}", movement_type="transfer_in"
        )
        self.assertEqual(
            (out.quantity, out.before_quantity, out.after_quantity), (-5, 10, 5)
        )
        self.assertEqual(
            (inc.quantity, inc.before_quantity, inc.after_quantity), (5, 0, 5)
        )
        self.assertEqual(out.created_by, self.source_operator)
        self.assertEqual(inc.created_by, self.destination_operator)

    def test_double_receive_does_not_credit_twice(self):
        transfer = self.approve_transfer(self.create_transfer())
        self.ship_transfer(transfer)
        self.receive_transfer(transfer)
        self.authenticate(self.destination_operator)
        response = self.client.post(
            self.endpoint(transfer, "receive"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        dest_stock = Stock.objects.get(product=self.product, warehouse=self.destination)
        self.assertEqual(dest_stock.quantity, 5)
        self.assertEqual(StockMovement.objects.count(), 2)

    # Cancellation, read access, and immutability.

    def test_manager_cannot_cancel(self):
        transfer = self.create_transfer()
        response = self.client.post(
            self.endpoint(transfer, "cancel"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_supervisor_cannot_cancel_own_request_even_if_created_directly(self):
        transfer = StockTransfer.objects.create(
            from_warehouse=self.source,
            to_warehouse=self.destination,
            product=self.product,
            quantity=2,
            requested_by=self.supervisor,
        )
        self.authenticate(self.supervisor)
        response = self.client.post(
            self.endpoint(transfer, "cancel"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_supervisor_can_cancel_another_users_pending_request(self):
        transfer = self.create_transfer(quantity=2)
        self.authenticate(self.supervisor)
        response = self.client.post(
            self.endpoint(transfer, "cancel"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        transfer.refresh_from_db()
        self.source_stock.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.StatusChoices.CANCELLED)
        self.assertEqual(self.source_stock.quantity, 10)
        self.assert_no_movements()

    def test_supervisor_can_cancel_an_approved_request_before_shipping(self):
        transfer = self.approve_transfer(self.create_transfer(quantity=2))
        response = self.client.post(
            self.endpoint(transfer, "cancel"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assert_no_movements()

    def test_shipped_transfer_cannot_be_cancelled_or_restored(self):
        transfer = self.approve_transfer(self.create_transfer())
        self.ship_transfer(transfer)
        self.authenticate(self.supervisor)
        response = self.client.post(
            self.endpoint(transfer, "cancel"), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        transfer.refresh_from_db()
        self.source_stock.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.StatusChoices.IN_TRANSIT)
        self.assertEqual(self.source_stock.quantity, 5)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_cannot_update_or_delete_transfer_directly(self):
        transfer = self.create_transfer()
        detail_url = f"{BASE_URL}{transfer.pk}/"
        patched = self.client.patch(detail_url, {"quantity": 1}, format="json")
        deleted = self.client.delete(detail_url)
        self.assertEqual(patched.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(deleted.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(StockTransfer.objects.filter(pk=transfer.pk).exists())

    def test_warehouse_operator_can_read_transfer_list(self):
        self.create_transfer()
        self.authenticate(self.source_operator)
        response = self.client.get(BASE_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unauthenticated_user_cannot_read_transfers(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(BASE_URL)
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
