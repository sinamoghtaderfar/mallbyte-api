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


class StockMovementAPITests(APITestCase):
    def setUp(self):
        cache.clear()

        self.inventory_manager = User.objects.create_user(
            email="inventory-manager-api@example.com",
            phone="+989511111111",
            full_name="Inventory Manager",
            password="StrongPass123!",
            is_staff=True,
        )

        self.seller = User.objects.create_user(
            email="inventory-seller-api@example.com",
            phone="+989522222222",
            full_name="Inventory Seller",
            password="StrongPass123!",
            is_seller=True,
        )

        inventory_role = Role.objects.get(
            name="inventory_manager",
        )

        UserRole.objects.create(
            user=self.inventory_manager,
            role=inventory_role,
            assigned_by=self.inventory_manager,
            is_active=True,
        )

        cache.clear()

        self.category = Category.objects.create(
            name="Stock Movement API Category",
            description="Inventory API test category",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Mechanical Keyboard API Test",
            description="Product for stock movement API tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="INV-API-KEYBOARD-001",
        )

        self.warehouse = Warehouse.objects.create(
            name="API Test Main Warehouse",
            code="API-MAIN",
            type=Warehouse.TypeChoices.MAIN,
            province="Bavaria",
            city="Bamberg",
            address="Inventory test address",
            postal_code="96047",
            phone="+499511111111",
            email="warehouse-api@example.com",
            manager_name="Warehouse Manager",
            manager_phone="+491761111111",
            is_active=True,
            created_by=self.inventory_manager,
        )

        self.stock = Stock.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            quantity=18,
            reserved_quantity=0,
            low_stock_threshold=5,
            updated_by=self.inventory_manager,
        )

        self.client.force_authenticate(
            user=self.inventory_manager,
        )

    def tearDown(self):
        cache.clear()

    def test_purchase_movement_increases_stock(self):
        response = self.client.post(
            "/api/inventory/stock-movements/",
            {
                "product": self.product.id,
                "warehouse": self.warehouse.id,
                "movement_type": "purchase",
                "quantity": 5,
                "reference_id": "PO-2026-001",
                "reason": "Supplier delivery",
                "notes": "Purchase movement test",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.stock.refresh_from_db()

        self.assertEqual(
            self.stock.quantity,
            23,
        )

        self.assertEqual(
            response.data["before_quantity"],
            18,
        )
        self.assertEqual(
            response.data["after_quantity"],
            23,
        )
        self.assertEqual(
            response.data["quantity"],
            5,
        )
        self.assertEqual(
            response.data["reference_id"],
            "PO-2026-001",
        )

    def test_damaged_movement_decreases_stock(self):
        response = self.client.post(
            "/api/inventory/stock-movements/",
            {
                "product": self.product.id,
                "warehouse": self.warehouse.id,
                "movement_type": "damaged",
                "quantity": -2,
                "reference_id": "DMG-2026-001",
                "reason": "Packaging damage",
                "notes": "Damaged during handling",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        self.stock.refresh_from_db()

        self.assertEqual(
            self.stock.quantity,
            16,
        )

        self.assertEqual(
            response.data["before_quantity"],
            18,
        )
        self.assertEqual(
            response.data["after_quantity"],
            16,
        )
        self.assertEqual(
            response.data["quantity"],
            -2,
        )

    def test_purchase_rejects_negative_quantity(self):
        response = self.client.post(
            "/api/inventory/stock-movements/",
            {
                "product": self.product.id,
                "warehouse": self.warehouse.id,
                "movement_type": "purchase",
                "quantity": -5,
                "reason": "Invalid purchase",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.stock.refresh_from_db()

        self.assertEqual(
            self.stock.quantity,
            18,
        )

    def test_damaged_rejects_positive_quantity(self):
        response = self.client.post(
            "/api/inventory/stock-movements/",
            {
                "product": self.product.id,
                "warehouse": self.warehouse.id,
                "movement_type": "damaged",
                "quantity": 2,
                "reason": "Invalid damaged movement",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.stock.refresh_from_db()

        self.assertEqual(
            self.stock.quantity,
            18,
        )

    def test_movement_cannot_reduce_stock_below_reserved_quantity(
        self,
    ):
        self.stock.quantity = 16
        self.stock.reserved_quantity = 3
        self.stock.save()

        response = self.client.post(
            "/api/inventory/stock-movements/",
            {
                "product": self.product.id,
                "warehouse": self.warehouse.id,
                "movement_type": "damaged",
                "quantity": -14,
                "reason": "Attempt to remove reserved stock",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.stock.refresh_from_db()

        self.assertEqual(
            self.stock.quantity,
            16,
        )
        self.assertEqual(
            self.stock.reserved_quantity,
            3,
        )

    def test_stock_movement_list_contains_audit_fields(self):
        StockMovement.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            movement_type=StockMovement.MovementType.PURCHASE,
            quantity=5,
            reference_id="PO-AUDIT-001",
            reason="Audit test",
            notes="Audit notes",
            created_by=self.inventory_manager,
        )

        response = self.client.get(
            "/api/inventory/stock-movements/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        movement = response.data["results"][0]

        self.assertEqual(
            movement["product_sku"],
            "INV-API-KEYBOARD-001",
        )
        self.assertEqual(
            movement["warehouse_code"],
            "API-MAIN",
        )
        self.assertEqual(
            movement["reason"],
            "Audit test",
        )
        self.assertEqual(
            movement["notes"],
            "Audit notes",
        )
        self.assertEqual(
            movement["before_quantity"],
            18,
        )
        self.assertEqual(
            movement["after_quantity"],
            23,
        )

    def test_existing_movement_cannot_be_updated(self):
        movement = StockMovement.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            movement_type=StockMovement.MovementType.PURCHASE,
            quantity=5,
            reason="Original movement",
            created_by=self.inventory_manager,
        )

        response = self.client.patch(
            f"/api/inventory/stock-movements/{movement.id}/",
            {
                "quantity": 100,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_existing_movement_cannot_be_deleted(self):
        movement = StockMovement.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            movement_type=StockMovement.MovementType.PURCHASE,
            quantity=5,
            reason="Original movement",
            created_by=self.inventory_manager,
        )

        response = self.client.delete(
            f"/api/inventory/stock-movements/{movement.id}/",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        self.assertTrue(
            StockMovement.objects.filter(
                id=movement.id,
            ).exists()
        )
