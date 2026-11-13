from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.inventory.models import StockMovement
from apps.orders.models import Order, OrderStatusHistory
from apps.payments.models import Payment, PaymentEvent
from apps.payments.tests import test_payment_integrity as integrity


@override_settings(SETTLEMENTS_ALLOW_MOCK_SUCCESS=True)
class PaymentActionTransactionTests(APITestCase):
    setUp = integrity.PaymentIntegrityTests.setUp

    def payment(self):
        return Payment.objects.create(order=self.order, user=self.customer, amount=self.order.total_amount)

    def assert_unchanged(self, payment):
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.stock.refresh_from_db()
        self.assertEqual(payment.status, Payment.StatusChoices.PENDING)
        self.assertEqual(self.order.status, Order.StatusChoices.PENDING_PAYMENT)
        self.assertEqual(self.order.payment_status, Order.PaymentStatusChoices.UNPAID)
        self.assertEqual(self.stock.quantity, 10)
        self.assertEqual(self.stock.reserved_quantity, 2)
        self.assertFalse(PaymentEvent.objects.filter(payment=payment).exists())
        self.assertFalse(OrderStatusHistory.objects.filter(order=self.order).exists())
        self.assertFalse(StockMovement.objects.exists())

    def failed_notification(self, action):
        payment = self.payment()
        with patch("apps.payments.views.create_payment_notification", side_effect=RuntimeError("Notification unavailable")):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/payments/payments/{payment.pk}/{action}/", {}, format="json")
        self.assert_unchanged(payment)

    def test_success_notification_failure_rolls_back_payment_order_and_inventory(self):
        self.failed_notification("mark-success")

    def test_failed_notification_rolls_back_payment_and_order(self):
        self.failed_notification("mark-failed")

    def test_cancel_notification_failure_rolls_back_payment(self):
        self.failed_notification("cancel")

    def test_audit_event_failure_rolls_back_payment_success(self):
        payment = self.payment()
        with patch("apps.payments.views.PaymentEvent.objects.create", side_effect=RuntimeError("Audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/payments/payments/{payment.pk}/mark-success/", {}, format="json")
        self.assert_unchanged(payment)
