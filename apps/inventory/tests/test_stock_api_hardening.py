from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from apps.inventory.models import (
    Stock,
    StockMovement,
    Warehouse,
)
from apps.products.models import Category, Product
from apps.rbac.models import Role, UserRole

User = get_user_model()

STOCKS_URL = "/api/inventory/stocks/"
MOVEMENTS_URL = "/api/inventory/stock-movements/"


class StockAPIHardeningTests(APITestCase):

    def setUp(self):
        cache.clear()

        self.manager = User.objects.create_user(
            email="hardening-manager@example.com",
            phone="+989511111121",
            full_name="Inventory Manager",
            password="StrongPass123!",
            is_staff=True,
        )

        self.supervisor = User.objects.create_user(
            email="hardening-supervisor@example.com",
            phone="+989511111122",
            full_name="Inventory Supervisor",
            password="StrongPass123!",
            is_staff=True,
        )

        self.seller = User.objects.create_user(
            email="hardening-seller@example.com",
            phone="+989511111123",
            full_name="Test Seller",
            password="StrongPass123!",
            is_seller=True,
        )

        for user, role_name in (
            (self.manager, "inventory_manager"),
            (self.supervisor, "inventory_supervisor"),
        ):
            UserRole.objects.create(
                user=user,
                role=Role.objects.get(name=role_name),
                assigned_by=self.manager,
                is_active=True,
            )

        self.category = Category.objects.create(
            name="Inventory Hardening",
            description="Security regression tests",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Test Keyboard",
            description="Inventory test product",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="HARDENING-KEYBOARD-001",
        )

        self.main = self.create_warehouse(
            "Main",
            "HARDEN-MAIN",
        )

        self.branch = self.create_warehouse(
            "Branch",
            "HARDEN-BRANCH",
        )

        self.stock = Stock.objects.create(
            product=self.product,
            warehouse=self.main,
            quantity=18,
            reserved_quantity=2,
            low_stock_threshold=5,
            updated_by=self.manager,
        )

        self.authenticate(self.manager)

    def tearDown(self):
        cache.clear()

    def create_warehouse(self, name, code):
        return Warehouse.objects.create(
            name=f"Hardening {name}",
            code=code,
            type=Warehouse.TypeChoices.MAIN,
            province="Bavaria",
            city="Bamberg",
            address="Test warehouse address",
            postal_code="96047",
            phone="+499511111111",
            email=f"{code.lower()}@example.com",
            manager_name="Test Manager",
            manager_phone="+491761111111",
            is_active=True,
            created_by=self.manager,
        )

    def authenticate(self, user):
        cache.clear()
        self.client.force_authenticate(user=user)

    def stock_detail_url(self):
        return f"{STOCKS_URL}{self.stock.pk}/"

    def movement_payload(self, **overrides):
        payload = {
            "product": self.product.pk,
            "warehouse": self.main.pk,
            "movement_type": "adjustment",
            "quantity": -2,
            "reason": "Cycle count discrepancy",
        }

        payload.update(overrides)
        return payload

    def assert_original_stock(self):
        self.stock.refresh_from_db()

        self.assertEqual(self.stock.quantity, 18)
        self.assertEqual(
            self.stock.reserved_quantity,
            2,
        )

    def test_can_create_empty_stock_record(self):
        response = self.client.post(
            STOCKS_URL,
            {
                "product": self.product.pk,
                "warehouse": self.branch.pk,
                "low_stock_threshold": 3,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        stock = Stock.objects.get(
            product=self.product,
            warehouse=self.branch,
        )

        self.assertEqual(stock.quantity, 0)
        self.assertEqual(stock.reserved_quantity, 0)
        self.assertEqual(stock.low_stock_threshold, 3)

        self.assertFalse(StockMovement.objects.exists())

    def test_cannot_set_initial_stock_directly(self):
        response = self.client.post(
            STOCKS_URL,
            {
                "product": self.product.pk,
                "warehouse": self.branch.pk,
                "quantity": 100,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertIn(
            "quantity",
            response.data,
        )

        self.assertFalse(
            Stock.objects.filter(
                product=self.product,
                warehouse=self.branch,
            ).exists()
        )

    def test_cannot_set_initial_reservation(self):
        response = self.client.post(
            STOCKS_URL,
            {
                "product": self.product.pk,
                "warehouse": self.branch.pk,
                "reserved_quantity": 5,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertIn(
            "reserved_quantity",
            response.data,
        )

    def test_cannot_patch_stock_quantity(self):
        response = self.client.patch(
            self.stock_detail_url(),
            {"quantity": 100},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertIn("quantity", response.data)

        self.assert_original_stock()

        self.assertEqual(
            StockMovement.objects.count(),
            0,
        )

    def test_cannot_patch_reserved_quantity(self):
        response = self.client.patch(
            self.stock_detail_url(),
            {"reserved_quantity": 0},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertIn(
            "reserved_quantity",
            response.data,
        )

        self.assert_original_stock()

    def test_can_update_stock_metadata(self):
        response = self.client.patch(
            self.stock_detail_url(),
            {
                "low_stock_threshold": 8,
                "aisle": "A3",
                "shelf": "S2",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        self.stock.refresh_from_db()

        self.assertEqual(
            self.stock.low_stock_threshold,
            8,
        )

        self.assertEqual(self.stock.aisle, "A3")
        self.assertEqual(self.stock.shelf, "S2")

        self.assert_original_stock()

        self.assertEqual(
            StockMovement.objects.count(),
            0,
        )

    def test_cannot_reassign_stock_warehouse(self):
        response = self.client.patch(
            self.stock_detail_url(),
            {"warehouse": self.branch.pk},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.stock.refresh_from_db()

        self.assertEqual(
            self.stock.warehouse_id,
            self.main.pk,
        )

    def test_cannot_delete_stock_record(self):
        response = self.client.delete(self.stock_detail_url())

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        self.assertTrue(Stock.objects.filter(pk=self.stock.pk).exists())

    def test_cannot_create_movement_without_reason(self):
        payload = self.movement_payload()
        payload.pop("reason")

        response = self.client.post(
            MOVEMENTS_URL,
            payload,
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assert_original_stock()

        self.assertFalse(StockMovement.objects.exists())

    def test_cannot_create_movement_with_blank_reason(self):
        response = self.client.post(
            MOVEMENTS_URL,
            self.movement_payload(reason="   "),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assert_original_stock()

    def test_cannot_manually_create_sale(self):
        response = self.client.post(
            MOVEMENTS_URL,
            self.movement_payload(
                movement_type="sale",
            ),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assert_original_stock()

        self.assertFalse(StockMovement.objects.exists())

    def test_cannot_manually_create_transfer_movements(self):
        for movement_type, quantity in (
            ("transfer_out", -2),
            ("transfer_in", 2),
        ):
            with self.subTest(movement_type=movement_type):
                response = self.client.post(
                    MOVEMENTS_URL,
                    self.movement_payload(
                        movement_type=movement_type,
                        quantity=quantity,
                    ),
                    format="json",
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )

        self.assert_original_stock()

        self.assertFalse(StockMovement.objects.exists())

    def test_valid_adjustment_records_full_audit(self):
        response = self.client.post(
            MOVEMENTS_URL,
            self.movement_payload(
                created_by=self.seller.pk,
                reason="  Cycle count discrepancy  ",
            ),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        movement = StockMovement.objects.get(pk=response.data["id"])

        self.stock.refresh_from_db()

        self.assertEqual(self.stock.quantity, 16)
        self.assertEqual(
            self.stock.reserved_quantity,
            2,
        )

        self.assertEqual(
            movement.before_quantity,
            18,
        )
        self.assertEqual(
            movement.after_quantity,
            16,
        )

        self.assertEqual(
            movement.reason,
            "Cycle count discrepancy",
        )

        # Identity must come from the authenticated user,
        # not from the request payload.
        self.assertEqual(
            movement.created_by_id,
            self.manager.pk,
        )

    def test_cannot_remove_reserved_stock(self):
        response = self.client.post(
            MOVEMENTS_URL,
            self.movement_payload(
                movement_type="damaged",
                quantity=-17,
                reason="Damaged inventory",
            ),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assert_original_stock()

        self.assertFalse(StockMovement.objects.exists())

    def test_supervisor_can_read_but_cannot_modify(self):
        self.authenticate(self.supervisor)

        read_response = self.client.get(STOCKS_URL)

        self.assertEqual(
            read_response.status_code,
            status.HTTP_200_OK,
        )

        update_response = self.client.patch(
            self.stock_detail_url(),
            {"low_stock_threshold": 10},
            format="json",
        )

        self.assertEqual(
            update_response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        movement_response = self.client.post(
            MOVEMENTS_URL,
            self.movement_payload(),
            format="json",
        )

        self.assertEqual(
            movement_response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assert_original_stock()
