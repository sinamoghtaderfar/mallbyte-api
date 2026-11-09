from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase, APITransactionTestCase

from apps.returns.models import ReturnItem, ReturnRequest, ReturnStatusHistory
from apps.returns.services import create_return_request, mark_return_refunded
from apps.returns.tests import test_returns_flow as flow
from apps.returns.tests.helpers import record_verified_return_evidence
from apps.settlements.models import ItemAllocation


class ReturnRefundIntegrityTests(APITestCase):
    setUp = flow.ReturnsFlowTests.setUp

    def claim(self, quantity=1):
        return create_return_request(
            customer=self.customer, order=self.order,
            items=[{"order_item": self.order_item, "quantity": quantity}],
            reason=ReturnRequest.Reason.DAMAGED,
            requested_resolution=ReturnRequest.RequestedResolution.REFUND,
            refund_method=ReturnRequest.RefundMethod.ORIGINAL_PAYMENT,
        )

    def discount(self, value):
        self.order.discount_amount = value
        self.order.save(update_fields=["discount_amount", "total_amount", "updated_at"])

    def test_legacy_order_refund_deducts_order_discount(self):
        self.discount(Decimal("50000"))
        claim = self.claim()
        self.assertEqual(claim.total_requested_amount, Decimal("75000.00"))
        self.assertEqual(claim.items.get().requested_refund_amount, Decimal("75000.00"))

    def test_partial_quantity_refunds_sum_to_discounted_consideration(self):
        self.discount(Decimal("1"))
        first = self.claim()
        second = self.claim()
        self.assertEqual(first.total_requested_amount + second.total_requested_amount, Decimal("199999.00"))
        self.assertEqual(first.items.get().quantity + second.items.get().quantity, 2)

    def test_cancelled_claim_releases_refundable_quantity_and_amount(self):
        self.discount(Decimal("50000"))
        first = self.claim()
        first.status = ReturnRequest.Status.CANCELLED
        first.save(update_fields=["status", "updated_at"])
        second = self.claim(quantity=2)
        self.assertEqual(second.total_requested_amount, Decimal("150000.00"))

    def test_snapshot_consideration_is_used_without_current_product_price(self):
        self.discount(Decimal("50000"))
        ItemAllocation.objects.create(
            order_item=self.order_item, seller=self.product.seller,
            quantity=2, gross=200000, discount=50000,
            shipping=0, tax=0, charged=150000, merchandise_net=150000,
            commission_rate=0, commission=0, seller_payable=150000,
        )
        self.product.price = Decimal("999999")
        self.product.save(update_fields=["price"])
        self.assertEqual(self.claim().total_requested_amount, Decimal("75000.00"))

    def test_duplicate_items_return_400_and_do_not_create_partial_claim(self):
        self.client.force_authenticate(self.customer)
        result = self.client.post(reverse("return-request-list"), {
            "order": self.order.pk,
            "items": [{"order_item": self.order_item.pk, "quantity": 1}] * 2,
        }, format="json")
        self.assertEqual(result.status_code, 400, result.data)
        self.assertFalse(ReturnRequest.objects.exists())

    @override_settings(SETTLEMENTS_LEDGER_ENABLED=False)
    def test_ledger_flag_cannot_bypass_verified_refund_evidence(self):
        claim = self.claim()
        claim.status = ReturnRequest.Status.ITEM_RECEIVED
        claim.total_approved_amount = claim.total_requested_amount
        claim.save(update_fields=["status", "total_approved_amount", "updated_at"])
        self.client.force_authenticate(self.admin_user)
        result = self.client.post(reverse("return-request-mark-refunded", args=[claim.pk]), {}, format="json")
        self.assertEqual(result.status_code, 400, result.data)
        claim.refresh_from_db()
        self.assertEqual(claim.status, ReturnRequest.Status.ITEM_RECEIVED)

    @override_settings(SETTLEMENTS_LEDGER_ENABLED=False)
    def test_verified_evidence_allows_refund_completion_with_ledger_disabled(self):
        claim = self.claim()
        claim.status = ReturnRequest.Status.ITEM_RECEIVED
        claim.total_approved_amount = claim.total_requested_amount
        claim.save(update_fields=["status", "total_approved_amount", "updated_at"])
        ReturnItem.objects.filter(return_request=claim).update(approved_refund_amount=claim.total_requested_amount)
        record_verified_return_evidence(claim)
        result = mark_return_refunded(return_request=claim, user=self.admin_user)
        self.assertEqual(result.status, ReturnRequest.Status.REFUNDED)

    def test_full_discount_has_no_monetary_refund_claim(self):
        self.discount(self.order.subtotal)
        self.assertEqual(self.claim(quantity=2).total_requested_amount, Decimal("0.00"))

    def test_large_valid_order_amount_does_not_overflow_return_storage(self):
        self.order_item.unit_price = Decimal("1000000000")
        self.order_item.save(update_fields=["unit_price", "total_price"])
        self.order.subtotal = Decimal("2000000000")
        self.order.save(update_fields=["subtotal", "total_amount", "updated_at"])
        claim = self.claim(quantity=2)
        claim.refresh_from_db()
        self.assertEqual(claim.total_requested_amount, Decimal("2000000000.00"))

    def test_database_rejects_approval_above_requested_amount(self):
        claim = self.claim()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReturnRequest.objects.filter(pk=claim.pk).update(total_approved_amount=claim.total_requested_amount + 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReturnItem.objects.filter(return_request=claim).update(approved_refund_amount=claim.total_requested_amount + 1)

    def test_refund_completion_replay_has_one_history_event(self):
        claim = self.claim()
        claim.status = ReturnRequest.Status.ITEM_RECEIVED
        claim.total_approved_amount = claim.total_requested_amount
        claim.save(update_fields=["status", "total_approved_amount", "updated_at"])
        record_verified_return_evidence(claim)
        first = mark_return_refunded(return_request=claim, user=self.admin_user)
        second = mark_return_refunded(return_request=claim, user=self.admin_user)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ReturnStatusHistory.objects.filter(return_request=claim, new_status="refunded").count(), 1)

    def test_quantity_rounding_remainder_is_refunded_only_once(self):
        self.order_item.quantity = 3
        self.order_item.unit_price = Decimal("1")
        self.order_item.save(update_fields=["quantity", "unit_price", "total_price"])
        self.order.subtotal = Decimal("3")
        self.order.discount_amount = Decimal("1")
        self.order.save(update_fields=["subtotal", "discount_amount", "total_amount", "updated_at"])
        amounts = [self.claim().total_requested_amount for _ in range(3)]
        self.assertEqual(amounts, [Decimal("0.67"), Decimal("0.67"), Decimal("0.66")])


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class ReturnRefundConcurrencyTests(APITransactionTestCase):
    setUp = flow.ReturnsFlowTests.setUp
    claim = ReturnRefundIntegrityTests.claim

    def test_concurrent_claims_do_not_exceed_item_quantity_or_net_amount(self):
        barrier = Barrier(2)

        def create_claim():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return self.claim(quantity=2).pk
                except ValidationError:
                    return None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create_claim) for _ in range(2)]
            result = [future.result(timeout=10) for future in futures]
        self.assertEqual(len([value for value in result if value is not None]), 1)
        self.assertEqual(ReturnRequest.objects.count(), 1)
        self.assertEqual(ReturnItem.objects.get().quantity, 2)
        self.assertEqual(ReturnRequest.objects.get().total_requested_amount, Decimal("200000.00"))
