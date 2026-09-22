from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.orders.models import Order, OrderStatusHistory
from apps.shipping.models import Shipment

User = get_user_model()


class OrderStatusIntegrityTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            phone="+989100002001",
            email="order-integrity-admin@example.com",
            full_name="Order Admin",
            password="TestPassword123!",
        )

        self.customer = User.objects.create_user(
            phone="+989100002002",
            email="order-integrity-customer@example.com",
            full_name="Test Customer",
            password="TestPassword123!",
        )

        self.order = Order.objects.create(
            user=self.customer,
            subtotal=Decimal("100000"),
            receiver_name="Test Customer",
            receiver_phone="+989100002002",
            province="Tehran",
            city="Tehran",
            address="Test address",
            postal_code="1234567890",
        )

        self.client.force_authenticate(user=self.admin)

    def update_status(self, new_status):
        return self.client.post(
            f"/api/orders/orders/{self.order.pk}/update-status/",
            {
                "status": new_status,
                "note": "Order integrity test.",
            },
            format="json",
        )

    def mark_order_paid(self):
        self.order.status = Order.StatusChoices.PAID
        self.order.payment_status = Order.PaymentStatusChoices.PAID
        self.order.save(
            update_fields=[
                "status",
                "payment_status",
                "total_amount",
                "updated_at",
            ]
        )

    def test_admin_cannot_mark_unpaid_order_paid(self):
        response = self.update_status("paid")

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.order.refresh_from_db()

        self.assertEqual(
            self.order.status,
            Order.StatusChoices.PENDING_PAYMENT,
        )

    def test_admin_cannot_skip_payment(self):
        for next_status in (
            "processing",
            "shipped",
            "delivered",
            "refunded",
        ):
            with self.subTest(next_status=next_status):
                response = self.update_status(next_status)

                self.assertEqual(
                    response.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )

        self.order.refresh_from_db()

        self.assertEqual(
            self.order.status,
            Order.StatusChoices.PENDING_PAYMENT,
        )

        self.assertFalse(OrderStatusHistory.objects.filter(order=self.order).exists())

    def test_admin_can_start_processing_paid_order(self):
        self.mark_order_paid()

        response = self.update_status("processing")

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        self.order.refresh_from_db()

        self.assertEqual(
            self.order.status,
            Order.StatusChoices.PROCESSING,
        )

        self.assertTrue(
            OrderStatusHistory.objects.filter(
                order=self.order,
                old_status=Order.StatusChoices.PAID,
                new_status=Order.StatusChoices.PROCESSING,
            ).exists()
        )

    def test_admin_cannot_mark_paid_order_refunded(self):
        self.mark_order_paid()

        response = self.update_status("refunded")

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.order.refresh_from_db()

        self.assertEqual(
            self.order.status,
            Order.StatusChoices.PAID,
        )

    def test_processing_order_is_eligible_for_shipping(self):
        self.mark_order_paid()
        self.order.status = Order.StatusChoices.PROCESSING
        self.order.save(
            update_fields=[
                "status",
                "total_amount",
                "updated_at",
            ]
        )

        response = self.client.get("/api/shipping/shipments/eligible-orders/")

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        eligible_ids = {item["id"] for item in response.data}

        self.assertIn(self.order.pk, eligible_ids)

    def test_processing_order_can_create_shipment(self):
        self.mark_order_paid()
        self.order.status = Order.StatusChoices.PROCESSING
        self.order.save(
            update_fields=[
                "status",
                "total_amount",
                "updated_at",
            ]
        )

        response = self.client.post(
            "/api/shipping/shipments/",
            {
                "order": self.order.pk,
                "carrier": "dhl",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        self.assertTrue(Shipment.objects.filter(order=self.order).exists())

    def test_shipment_ready_updates_order_status(self):
        self.mark_order_paid()

        shipment = Shipment.create_from_order(
            self.order,
            created_by=self.admin,
        )

        response = self.client.post(
            f"/api/shipping/shipments/" f"{shipment.pk}/mark-ready/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        self.order.refresh_from_db()
        shipment.refresh_from_db()

        self.assertEqual(
            self.order.status,
            Order.StatusChoices.PROCESSING,
        )

        self.assertEqual(
            shipment.status,
            Shipment.StatusChoices.READY_TO_SHIP,
        )

        self.assertTrue(
            OrderStatusHistory.objects.filter(
                order=self.order,
                new_status=Order.StatusChoices.PROCESSING,
            ).exists()
        )
