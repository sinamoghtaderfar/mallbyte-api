from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.inventory.models import Stock, StockMovement, Warehouse
from apps.notifications.models import Notification
from apps.products.models import Category, Product


class InventoryNotificationTests(TestCase):
    def create_test_user(
        self,
        *,
        phone,
        email,
        full_name,
        password="testpass123",
        is_staff=False,
        is_superuser=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        user.set_password(password)
        user.save()
        return user

    def setUp(self):
        self.seller = self.create_test_user(
            phone="+989500000001",
            email="seller_inventory@example.com",
            full_name="Inventory Seller",
            is_staff=True,
        )

        self.admin_user = self.create_test_user(
            phone="+989500000002",
            email="admin_inventory@example.com",
            full_name="Inventory Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.category = Category.objects.create(
            name="Inventory Test Category",
            description="Test category",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Inventory Test Product",
            description="Product for inventory notification tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="INV-NOTIF-SKU-001",
        )

        self.warehouse = Warehouse.objects.create(
            name="Inventory Test Warehouse",
            code="INV-WH-001",
            type=Warehouse.TypeChoices.MAIN,
            province="Tehran",
            city="Tehran",
            address="Test warehouse address",
            postal_code="1234567890",
            phone="+982100000000",
            email="inventory-warehouse@example.com",
            manager_name="Warehouse Manager",
            manager_phone="+989500000003",
            is_active=True,
            created_by=self.admin_user,
        )

    def create_stock(self, *, quantity=10, reserved_quantity=0, low_stock_threshold=5):
        return Stock.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            quantity=quantity,
            reserved_quantity=reserved_quantity,
            low_stock_threshold=low_stock_threshold,
            updated_by=self.admin_user,
        )

    def test_low_stock_notification_is_created_when_stock_crosses_threshold(self):
        stock = self.create_stock(
            quantity=10,
            reserved_quantity=0,
            low_stock_threshold=5,
        )

        movement = StockMovement.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            movement_type=StockMovement.MovementType.DAMAGED,
            quantity=-6,
            reason="Damaged items removed from stock.",
            created_by=self.admin_user,
        )

        stock.refresh_from_db()

        self.assertEqual(stock.quantity, 4)
        self.assertEqual(movement.before_quantity, 10)
        self.assertEqual(movement.after_quantity, 4)

        self.assertTrue(
            Notification.objects.filter(
                user=self.seller,
                notification_type=Notification.NotificationType.INVENTORY,
                related_object_type="stock",
                related_object_id=str(stock.pk),
                title="Low stock alert",
            ).exists()
        )

    def test_low_stock_notification_is_not_created_for_stock_increase(self):
        stock = self.create_stock(
            quantity=10,
            reserved_quantity=0,
            low_stock_threshold=5,
        )

        StockMovement.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            movement_type=StockMovement.MovementType.PURCHASE,
            quantity=5,
            reason="New purchase stock.",
            created_by=self.admin_user,
        )

        stock.refresh_from_db()

        self.assertEqual(stock.quantity, 15)

        self.assertFalse(
            Notification.objects.filter(
                user=self.seller,
                title="Low stock alert",
                related_object_type="stock",
                related_object_id=str(stock.pk),
            ).exists()
        )

    def test_low_stock_notification_is_not_created_when_stock_was_already_low(self):
        stock = self.create_stock(
            quantity=5,
            reserved_quantity=0,
            low_stock_threshold=5,
        )

        StockMovement.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            movement_type=StockMovement.MovementType.DAMAGED,
            quantity=-1,
            reason="One damaged item removed.",
            created_by=self.admin_user,
        )

        stock.refresh_from_db()

        self.assertEqual(stock.quantity, 4)

        self.assertFalse(
            Notification.objects.filter(
                user=self.seller,
                title="Low stock alert",
                related_object_type="stock",
                related_object_id=str(stock.pk),
            ).exists()
        )

    def test_low_stock_notification_is_not_created_when_stock_stays_above_threshold(
        self,
    ):
        stock = self.create_stock(
            quantity=10,
            reserved_quantity=0,
            low_stock_threshold=5,
        )

        StockMovement.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            movement_type=StockMovement.MovementType.DAMAGED,
            quantity=-2,
            reason="Two damaged items removed.",
            created_by=self.admin_user,
        )

        stock.refresh_from_db()

        self.assertEqual(stock.quantity, 8)

        self.assertFalse(
            Notification.objects.filter(
                user=self.seller,
                title="Low stock alert",
                related_object_type="stock",
                related_object_id=str(stock.pk),
            ).exists()
        )
