from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.inventory.models import Stock, Warehouse
from apps.notifications.models import Notification
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Category, Product


class PaymentNotificationTests(APITestCase):
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
            phone="+989300000001",
            email="admin_payments@example.com",
            full_name="Payments Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989300000002",
            email="customer_payments@example.com",
            full_name="Payments Customer",
        )

        self.category = Category.objects.create(
            name="Payments Test Category",
            description="Test category",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Payments Test Product",
            description="Product for payment notification tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="PAYMENT-NOTIF-SKU-001",
        )

        self.warehouse = Warehouse.objects.create(
            name="Payments Test Warehouse",
            code="PAY-WH-001",
            type=Warehouse.TypeChoices.MAIN,
            province="Tehran",
            city="Tehran",
            address="Test warehouse address",
            postal_code="1234567890",
            phone="+982100000000",
            email="payment-warehouse@example.com",
            manager_name="Warehouse Manager",
            manager_phone="+989300000003",
            is_active=True,
            created_by=self.admin_user,
        )

        self.stock = Stock.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            quantity=10,
            reserved_quantity=1,
            low_stock_threshold=2,
            updated_by=self.admin_user,
        )

        self.order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Payments Customer",
            receiver_phone="+989300000002",
            province="Tehran",
            city="Tehran",
            address="Customer test address",
            postal_code="1234567890",
        )

        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            warehouse=self.warehouse,
            quantity=1,
            unit_price=Decimal("100000"),
            total_price=Decimal("100000"),
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def create_payment(self):
        return Payment.objects.create(
            order=self.order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            amount=self.order.total_amount,
            currency="IRR",
            created_by=self.customer,
        )

    def assert_payment_notification_exists(self, *, payment, title):
        self.assertTrue(
            Notification.objects.filter(
                user=self.customer,
                notification_type=Notification.NotificationType.PAYMENT,
                related_object_type="payment",
                related_object_id=str(payment.pk),
                title=title,
            ).exists()
        )

    def test_mark_success_creates_payment_successful_notification(self):
        self.authenticate_customer()

        payment = self.create_payment()

        url = reverse("payment-mark-success", args=[payment.pk])

        response = self.client.post(
            url,
            data={
                "gateway_reference": "MOCK-REF-123",
                "gateway_response": {
                    "status": "ok",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payment.refresh_from_db()
        self.order.refresh_from_db()

        self.assertEqual(payment.status, Payment.StatusChoices.SUCCESS)
        self.assertEqual(self.order.payment_status, Order.PaymentStatusChoices.PAID)

        self.assert_payment_notification_exists(
            payment=payment,
            title="Payment successful",
        )

    def test_mark_failed_creates_payment_failed_notification(self):
        self.authenticate_customer()

        payment = self.create_payment()

        url = reverse("payment-mark-failed", args=[payment.pk])

        response = self.client.post(
            url,
            data={
                "reason": "Gateway declined payment.",
                "gateway_response": {
                    "error": "declined",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payment.refresh_from_db()

        self.assertEqual(payment.status, Payment.StatusChoices.FAILED)

        self.assert_payment_notification_exists(
            payment=payment,
            title="Payment failed",
        )

    def test_cancel_creates_payment_cancelled_notification(self):
        self.authenticate_customer()

        payment = self.create_payment()

        url = reverse("payment-cancel", args=[payment.pk])

        response = self.client.post(
            url,
            data={
                "reason": "User cancelled payment.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payment.refresh_from_db()

        self.assertEqual(payment.status, Payment.StatusChoices.CANCELLED)

        self.assert_payment_notification_exists(
            payment=payment,
            title="Payment cancelled",
        )
