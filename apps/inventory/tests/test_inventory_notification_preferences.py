from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.inventory.models import Stock, StockMovement, Warehouse
from apps.notifications.models import Notification, NotificationPreference
from apps.products.models import Category, Product


class InventoryNotificationPreferenceIntegrationTests(TestCase):
    def create_test_user(
        self,
        *,
        phone,
        email,
        full_name,
        password="testpass123",
        is_staff=False,
        is_superuser=False,
        is_seller=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
            is_seller=is_seller,
        )
        user.set_password(password)
        user.save()
        return user

    def setUp(self):
        self.admin_user = self.create_test_user(
            phone="+989720000001",
            email="admin_inventory_pref@example.com",
            full_name="Inventory Preference Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.seller_user = self.create_test_user(
            phone="+989720000002",
            email="seller_inventory_pref@example.com",
            full_name="Inventory Preference Seller",
            is_seller=True,
        )

        self.category = Category.objects.create(
            name="Inventory Preference Category",
            description="Test category",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.seller_user,
            category=self.category,
            name="Inventory Preference Product",
            description="Product for inventory preference tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="INVENTORY-PREF-SKU-001",
        )

        self.warehouse = Warehouse.objects.create(
            name="Inventory Preference Warehouse",
            code="INV-PREF-WH-001",
            type=Warehouse.TypeChoices.MAIN,
            province="Tehran",
            city="Tehran",
            address="Test warehouse address",
            postal_code="1234567890",
            phone="+982100000000",
            email="inventory-pref-warehouse@example.com",
            manager_name="Warehouse Manager",
            manager_phone="+989720000003",
            is_active=True,
            created_by=self.admin_user,
        )

        NotificationPreference.objects.create(
            user=self.seller_user,
            muted_notification_types=[
                Notification.NotificationType.INVENTORY,
            ],
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

    def test_muted_inventory_type_blocks_low_stock_notification(self):
        stock = self.create_stock(
            quantity=10,
            reserved_quantity=0,
            low_stock_threshold=5,
        )

        StockMovement.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            movement_type=StockMovement.MovementType.DAMAGED,
            quantity=-6,
            reason="Damaged items removed from stock.",
            created_by=self.admin_user,
        )

        stock.refresh_from_db()

        self.assertEqual(stock.quantity, 4)
        self.assertEqual(stock.available_quantity, 4)

        self.assertFalse(
            Notification.objects.filter(
                user=self.seller_user,
                notification_type=Notification.NotificationType.INVENTORY,
                related_object_type="stock",
                related_object_id=str(stock.pk),
                title="Low stock alert",
            ).exists()
        )
