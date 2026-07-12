from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.inventory.models import Stock, Warehouse
from apps.notifications.models import Notification
from apps.orders.models import Cart, CartItem, Order
from apps.products.models import Category, Product


class OrderNotificationTests(APITestCase):
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
        self.admin_user = self.create_test_user(
            phone="+989200000001",
            email="admin_orders@example.com",
            full_name="Orders Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989200000002",
            email="customer_orders@example.com",
            full_name="Orders Customer",
        )

        self.category = Category.objects.create(
            name="Orders Test Category",
            description="Test category",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Orders Test Product",
            description="Product for order notification tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="ORDER-NOTIF-SKU-001",
        )

        self.warehouse = Warehouse.objects.create(
            name="Orders Test Warehouse",
            code="ORD-WH-001",
            type=Warehouse.TypeChoices.MAIN,
            province="Tehran",
            city="Tehran",
            address="Test warehouse address",
            postal_code="1234567890",
            phone="+982100000000",
            email="warehouse@example.com",
            manager_name="Warehouse Manager",
            manager_phone="+989200000003",
            is_active=True,
            created_by=self.admin_user,
        )

        self.stock = Stock.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            quantity=10,
            reserved_quantity=0,
            low_stock_threshold=2,
            updated_by=self.admin_user,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def create_cart_with_item(self):
        cart, _created = Cart.objects.get_or_create(user=self.customer)

        CartItem.objects.create(
            cart=cart,
            product=self.product,
            quantity=1,
            unit_price=self.product.final_price,
        )

        return cart

    def checkout_order(self):
        self.authenticate_customer()
        self.create_cart_with_item()

        url = reverse("order-checkout")

        response = self.client.post(
            url,
            data={
                "receiver_name": "Orders Customer",
                "receiver_phone": "+989200000002",
                "province": "Tehran",
                "city": "Tehran",
                "address": "Customer test address",
                "postal_code": "1234567890",
                "customer_note": "Please deliver fast.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        return Order.objects.get(user=self.customer)

    def assert_order_notification_exists(self, *, order, title):
        self.assertTrue(
            Notification.objects.filter(
                user=self.customer,
                notification_type=Notification.NotificationType.ORDER,
                related_object_type="order",
                related_object_id=str(order.pk),
                title=title,
            ).exists()
        )

    def test_checkout_creates_order_created_notification(self):
        order = self.checkout_order()

        self.assert_order_notification_exists(
            order=order,
            title="Order created",
        )

    def test_customer_cancel_creates_order_cancelled_notification(self):
        order = self.checkout_order()

        url = reverse("order-cancel", args=[order.pk])

        cancel_response = self.client.post(url, data={}, format="json")

        self.assertEqual(cancel_response.status_code, status.HTTP_200_OK)

        order.refresh_from_db()

        self.assertEqual(order.status, Order.StatusChoices.CANCELLED)

        self.assert_order_notification_exists(
            order=order,
            title="Order cancelled",
        )

    def test_admin_status_update_creates_order_status_notification(self):
        order = self.checkout_order()

        self.authenticate_admin()

        url = reverse("order-update-status", args=[order.pk])

        response = self.client.post(
            url,
            data={
                "status": Order.StatusChoices.PROCESSING,
                "note": "Order is being prepared.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        order.refresh_from_db()

        self.assertEqual(order.status, Order.StatusChoices.PROCESSING)

        self.assert_order_notification_exists(
            order=order,
            title="Order status updated",
        )

    def test_paid_status_update_does_not_create_order_notification(self):
        order = self.checkout_order()

        self.authenticate_admin()

        before_count = Notification.objects.filter(
            user=self.customer,
            notification_type=Notification.NotificationType.ORDER,
            related_object_type="order",
            related_object_id=str(order.pk),
            title="Order status updated",
        ).count()

        url = reverse("order-update-status", args=[order.pk])

        response = self.client.post(
            url,
            data={
                "status": Order.StatusChoices.PAID,
                "note": "Payment status will be handled by payments app.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        after_count = Notification.objects.filter(
            user=self.customer,
            notification_type=Notification.NotificationType.ORDER,
            related_object_type="order",
            related_object_id=str(order.pk),
            title="Order status updated",
        ).count()

        self.assertEqual(before_count, after_count)
