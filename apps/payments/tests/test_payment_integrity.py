from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.inventory.models import Stock, StockMovement, Warehouse
from apps.orders.models import Order, OrderItem, OrderStatusHistory
from apps.payments.models import Payment, PaymentEvent
from apps.products.models import Category, Product

User = get_user_model()


class PaymentIntegrityTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            phone="+989100001001",
            email="payment-integrity-admin@example.com",
            full_name="Test Admin",
            password="TestPassword123!",
        )

        self.customer = User.objects.create_user(
            phone="+989100001002",
            email="payment-integrity-customer@example.com",
            full_name="Test Customer",
            password="TestPassword123!",
        )

        category = Category.objects.create(
            name="Payment Integrity Tests",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin,
            category=category,
            name="Test Keyboard",
            description="Payment integrity test product",
            price=Decimal("100000"),
            sku="PAYMENT-INTEGRITY-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

        self.warehouse = Warehouse.objects.create(
            name="Payment Integrity Warehouse",
            code="PAY-INTEGRITY",
            type=Warehouse.TypeChoices.MAIN,
            province="Tehran",
            city="Tehran",
            address="Test address",
            postal_code="1234567890",
            phone="+982100000001",
            manager_name="Test Manager",
            manager_phone="+989100001003",
        )

        self.stock = Stock.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            quantity=10,
            reserved_quantity=2,
        )

        self.order = Order.objects.create(
            user=self.customer,
            subtotal=Decimal("200000"),
            receiver_name="Test Customer",
            receiver_phone="+989100001002",
            province="Tehran",
            city="Tehran",
            address="Test address",
            postal_code="1234567890",
        )

        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            warehouse=self.warehouse,
            quantity=2,
            unit_price=Decimal("100000"),
        )

        self.client.force_authenticate(user=self.customer)

    def create_payment(self):
        return self.client.post(
            "/api/payments/payments/",
            {
                "order": self.order.pk,
                "provider": "mock",
            },
            format="json",
        )

    def mark_success(self, payment_id):
        return self.client.post(
            f"/api/payments/payments/{payment_id}/mark-success/",
            {
                "gateway_reference": f"MOCK-{payment_id}",
            },
            format="json",
        )

    def test_repeated_create_reuses_pending_payment(self):
        first = self.create_payment()
        second = self.create_payment()

        self.assertEqual(
            first.status_code,
            status.HTTP_201_CREATED,
            first.data,
        )
        self.assertEqual(
            second.status_code,
            status.HTTP_201_CREATED,
            second.data,
        )

        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(PaymentEvent.objects.count(), 1)

    def test_only_one_attempt_can_succeed(self):
        first = self.create_payment()
        self.assertEqual(first.status_code, 201, first.data)

        second = Payment.objects.create(
            order=self.order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            amount=self.order.total_amount,
        )

        result = self.mark_success(first.data["id"])
        self.assertEqual(result.status_code, 200, result.data)

        second.refresh_from_db()
        self.assertEqual(
            second.status,
            Payment.StatusChoices.CANCELLED,
        )

        retry = self.mark_success(second.pk)
        self.assertEqual(retry.status_code, 400)

        self.stock.refresh_from_db()
        self.order.refresh_from_db()

        self.assertEqual(self.stock.quantity, 8)
        self.assertEqual(self.stock.reserved_quantity, 0)
        self.assertEqual(
            self.order.payment_status,
            Order.PaymentStatusChoices.PAID,
        )

        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.SALE
            ).count(),
            1,
        )

        self.assertEqual(
            Payment.objects.filter(
                order=self.order,
                status=Payment.StatusChoices.SUCCESS,
            ).count(),
            1,
        )

        self.assertTrue(
            OrderStatusHistory.objects.filter(
                order=self.order,
                new_status=Order.StatusChoices.PAID,
            ).exists()
        )

    def test_failed_payment_requires_new_attempt(self):
        first = self.create_payment()
        self.assertEqual(first.status_code, 201, first.data)

        failed = self.client.post(
            f"/api/payments/payments/{first.data['id']}/mark-failed/",
            {"reason": "Mock payment failed"},
            format="json",
        )
        self.assertEqual(failed.status_code, 200, failed.data)

        retry_old = self.mark_success(first.data["id"])
        self.assertEqual(retry_old.status_code, 400)

        second = self.create_payment()
        self.assertEqual(second.status_code, 201, second.data)
        self.assertNotEqual(first.data["id"], second.data["id"])

        result = self.mark_success(second.data["id"])
        self.assertEqual(result.status_code, 200, result.data)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 8)
        self.assertEqual(self.stock.reserved_quantity, 0)

    def test_cancelling_pending_order_cancels_payment(self):
        payment = self.create_payment()
        self.assertEqual(payment.status_code, 201, payment.data)

        response = self.client.post(
            f"/api/orders/orders/{self.order.pk}/cancel/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.order.refresh_from_db()
        self.stock.refresh_from_db()

        attempt = Payment.objects.get(pk=payment.data["id"])

        self.assertEqual(
            self.order.status,
            Order.StatusChoices.CANCELLED,
        )
        self.assertEqual(
            attempt.status,
            Payment.StatusChoices.CANCELLED,
        )
        self.assertEqual(self.stock.quantity, 10)
        self.assertEqual(self.stock.reserved_quantity, 0)

        retry = self.mark_success(attempt.pk)
        self.assertEqual(retry.status_code, 400)

    def test_paid_order_cannot_be_cancelled_by_admin(self):
        payment = self.create_payment()
        self.assertEqual(payment.status_code, 201, payment.data)

        result = self.mark_success(payment.data["id"])
        self.assertEqual(result.status_code, 200, result.data)

        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            f"/api/orders/orders/{self.order.pk}/cancel/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        self.order.refresh_from_db()
        self.stock.refresh_from_db()

        self.assertEqual(
            self.order.status,
            Order.StatusChoices.PAID,
        )
        self.assertEqual(self.stock.quantity, 8)
        self.assertEqual(self.stock.reserved_quantity, 0)

    def test_wrong_payment_amount_is_rejected(self):
        payment = Payment.objects.create(
            order=self.order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            amount=Decimal("1000"),
        )

        response = self.mark_success(payment.pk)
        self.assertEqual(response.status_code, 400)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 10)
        self.assertEqual(self.stock.reserved_quantity, 2)

    def test_real_provider_cannot_be_completed_manually(self):
        response = self.client.post(
            "/api/payments/payments/",
            {
                "order": self.order.pk,
                "provider": "stripe",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        payment = Payment.objects.create(
            order=self.order,
            user=self.customer,
            provider=Payment.ProviderChoices.STRIPE,
            amount=self.order.total_amount,
        )

        response = self.mark_success(payment.pk)
        self.assertEqual(response.status_code, 400)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 10)
        self.assertEqual(self.stock.reserved_quantity, 2)
