from decimal import Decimal

from django.test import TestCase

from apps.orders.models import Order, OrderStatusHistory
from apps.payments.models import Payment
from apps.returns.models import ReturnItem, ReturnRequest
from apps.settlements.services import post_verified_refund
from apps.settlements.tests import test_settlement_services as accounting


class RefundedOrderConsistencyTests(TestCase):
    setUp = accounting.SettlementAccountingTests.setUp
    _snap_and_post = accounting.SettlementAccountingTests._snap_and_post

    def test_full_verified_refund_updates_payment_order_and_history_once(self):
        snapshots = self._snap_and_post()
        claim = ReturnRequest.objects.create(
            order=self.order, customer=self.customer, status=ReturnRequest.Status.ITEM_RECEIVED,
            total_requested_amount=300, total_approved_amount=300,
        )
        lines = []
        for snapshot in snapshots:
            ReturnItem.objects.create(
                return_request=claim, order_item_id=snapshot.order_item_id,
                quantity=1, requested_refund_amount=snapshot.charged,
                approved_refund_amount=snapshot.charged,
            )
            lines.append({
                "order_item_id": snapshot.order_item_id,
                "merchandise": str(snapshot.merchandise_net),
                "shipping": str(snapshot.shipping), "tax": str(snapshot.tax),
            })
        kwargs = {
            "payment_id": self.payment.pk, "return_request_id": claim.pk,
            "confirmed_amount": "300", "currency": "IRR", "gateway_reference": "full-proof-001",
            "idempotency_key": "full-proof-001", "lines": lines, "confirmed_at": self.now,
        }
        first = post_verified_refund(**kwargs)
        self.assertEqual(post_verified_refund(**kwargs).pk, first.pk)
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.StatusChoices.REFUNDED)
        self.assertEqual(self.order.status, Order.StatusChoices.REFUNDED)
        self.assertEqual(self.order.payment_status, Order.PaymentStatusChoices.REFUNDED)
        self.assertEqual(self.order.total_amount, Decimal("300"))
        self.assertEqual(OrderStatusHistory.objects.filter(order=self.order, new_status="refunded").count(), 1)
