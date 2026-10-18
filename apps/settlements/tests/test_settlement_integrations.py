"""Tests for feature-gated checkout/payment posting and signed financial events."""
import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Seller, User
from apps.inventory.models import Stock, Warehouse
from apps.orders.models import Cart, CartItem, Order, SellerOrderFulfillment
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.returns.models import ReturnItem, ReturnRequest
from apps.settlements.models import ItemAllocation, ConfirmedPayout, ConfirmedRefund, SellerLedgerEntry
from apps.settlements.services import seller_balance
from apps.settlements.settlement_policy import payout_eligibility

CAPTURE_SECRET = "capture-bridge-secret-integration-tests-unique-a"
REFUND_SECRET = "refund-bridge-secret-integration-tests-unique-b"
PAYOUT_SECRET = "payout-bridge-secret-integration-tests-unique-c"


@override_settings(
    SETTLEMENTS_LEDGER_ENABLED=True,
    SETTLEMENTS_ALLOW_MOCK_SUCCESS=True,
    SETTLEMENTS_ALLOW_SIGNED_MOCK_EVENTS=True,
    SETTLEMENTS_CAPTURE_BRIDGE_SECRET=CAPTURE_SECRET,
    SETTLEMENTS_REFUND_BRIDGE_SECRET=REFUND_SECRET,
    SETTLEMENTS_PAYOUT_BRIDGE_SECRET=PAYOUT_SECRET,
    SETTLEMENTS_PAYOUT_HOLD_DAYS=14,
)
class FinancialIntegrationTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="integration-admin5@example.com", full_name="Admin", password="testpass"
        )
        self.seller = User.objects.create_user(
            email="integration-seller5@example.com", full_name="Seller", password="testpass", is_seller=True
        )
        self.customer = User.objects.create_user(
            email="integration-customer5@example.com", full_name="Customer", password="testpass"
        )
        Seller.objects.create(
            user=self.seller, store_name="Settlement Integrated Store", store_slug="settlement-integrated-store",
            business_phone="09120000000", business_email="seller5@example.com",
            commission_rate=Decimal("10"), status=Seller.StatusChoices.APPROVED,
        )
        cat = Category.objects.create(name="Settlement Integration", slug="settle-integration")
        product = Product.objects.create(
            seller=self.seller, category=cat, name="Integrated Product", slug="settlement-integrated-product",
            description="test", sku="SETT-INT-5", price=Decimal("100"),
            status=Product.StatusChoices.APPROVED, is_active=True,
        )
        wh = Warehouse.objects.create(
            name="Integration Warehouse", code="SETT-INT-WH", type=Warehouse.TypeChoices.MAIN,
            province="Tehran", city="Tehran", address="test", postal_code="1234567890",
            phone="02100000000", manager_name="Warehouse Manager", manager_phone="09123456789",
        )
        Stock.objects.create(product=product, warehouse=wh, quantity=5, reserved_quantity=0)
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=product, quantity=1, unit_price=Decimal("100"))
        self.client.force_authenticate(user=self.customer)

    def checkout_and_payment(self):
        response = self.client.post(
            reverse("order-checkout"),
            {"receiver_name": "Customer", "receiver_phone": "09120000000", "province": "Tehran",
             "city": "Tehran", "address": "test", "postal_code": "1234567890", "shipping_cost": "0"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        order = Order.objects.get(pk=response.data["id"])
        self.assertEqual(ItemAllocation.objects.filter(order_item__order=order).count(), 1)
        self.assertEqual(ItemAllocation.objects.get(order_item__order=order).seller_id, self.seller.pk)
        create = self.client.post(reverse("payment-list"), {"order": order.pk, "provider": "mock"}, format="json")
        self.assertEqual(create.status_code, 201, create.data)
        return order, Payment.objects.get(pk=create.data["id"])

    def signed_post(self, name, payload, secret, *, tamper=False):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        stamp = str(int(timezone.now().timestamp()))
        digest = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        return self.client.post(
            reverse(name), data=raw, content_type="application/json",
            HTTP_X_SETTLEMENT_TIMESTAMP=stamp,
            HTTP_X_SETTLEMENT_SIGNATURE=("0" * 64 if tamper else digest),
        )

    def make_return(self, order, *, amount="50.00", status_value=ReturnRequest.Status.APPROVED):
        ret = ReturnRequest.objects.create(
            order=order, customer=self.customer, status=status_value,
            requested_resolution=ReturnRequest.RequestedResolution.REFUND,
            total_requested_amount=Decimal(amount), total_approved_amount=Decimal(amount),
        )
        item = order.items.get()
        ReturnItem.objects.create(
            return_request=ret, order_item=item, quantity=1,
            requested_refund_amount=Decimal(amount), approved_refund_amount=Decimal(amount),
            status=ReturnItem.ItemStatus.APPROVED,
        )
        return ret, item

    def test_checkout_snapshot_and_mock_payment_post_exactly_once(self):
        order, payment = self.checkout_and_payment()
        response = self.client.post(
            reverse("payment-mark-success", args=[payment.pk]),
            {"gateway_reference": "mock-pay-1"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(seller_balance(self.seller.pk, "IRR"), Decimal("90.00"))
        self.assertEqual(SellerLedgerEntry.objects.filter(kind="sale").count(), 1)
        self.assertEqual(self.client.post(reverse("payment-mark-success", args=[payment.pk]), {}, format="json").status_code, 400)
        self.assertEqual(SellerLedgerEntry.objects.filter(kind="sale").count(), 1)

    @override_settings(SETTLEMENTS_ALLOW_MOCK_SUCCESS=False)
    def test_direct_mock_success_is_blocked_but_verified_bridge_works(self):
        order, payment = self.checkout_and_payment()
        denied = self.client.post(reverse("payment-mark-success", args=[payment.pk]), {}, format="json")
        self.assertEqual(denied.status_code, 403)
        event = {
            "event": "payment.captured", "payment_id": payment.pk, "provider": "mock",
            "amount": "100.00", "currency": "IRR", "gateway_reference": "trusted-mock-capture-001",
            "confirmed_at": timezone.now().isoformat(),
        }
        self.assertEqual(self.signed_post("settlement-capture-confirmed", event, CAPTURE_SECRET, tamper=True).status_code, 403)
        first = self.signed_post("settlement-capture-confirmed", event, CAPTURE_SECRET)
        self.assertEqual(first.status_code, 200, first.data)
        repeat = self.signed_post("settlement-capture-confirmed", event, CAPTURE_SECRET)
        self.assertEqual(repeat.status_code, 200, repeat.data)
        self.assertEqual(SellerLedgerEntry.objects.filter(kind="sale").count(), 1)
        self.assertEqual(seller_balance(self.seller.pk, "IRR"), Decimal("90.00"))

    def test_signed_partial_refund_reverses_only_confirmed_amount(self):
        order, payment = self.checkout_and_payment()
        payment.mark_success(gateway_reference="manual-test-capture")
        ret, item = self.make_return(order)
        event = {
            "event": "refund.confirmed", "payment_id": payment.pk, "return_request_id": ret.pk,
            "provider": "mock", "confirmed_amount": "50.00", "currency": "IRR",
            "gateway_reference": "mock-refund-001", "idempotency_key": "test-refund-001",
            "confirmed_at": timezone.now().isoformat(),
            "lines": [{"order_item_id": item.pk, "merchandise": "50.00", "shipping": "0", "tax": "0"}],
        }
        self.assertEqual(self.signed_post("settlement-refund-confirmed", event, REFUND_SECRET, tamper=True).status_code, 403)
        response = self.signed_post("settlement-refund-confirmed", event, REFUND_SECRET)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.signed_post("settlement-refund-confirmed", event, REFUND_SECRET).status_code, 200)
        self.assertEqual(ConfirmedRefund.objects.count(), 1)
        self.assertEqual(seller_balance(self.seller.pk, "IRR"), Decimal("45.00"))
        self.assertEqual(SellerLedgerEntry.objects.filter(kind="refund").count(), 1)
        # The new financial contract must count a PARTIAL refund even though
        # Payment.status is still SUCCESS (the original legacy reporting missed it).
        from apps.analytics.financial import get_financial_cashflow
        from apps.analytics.financial_reporting import get_reporting_financial
        financial = get_financial_cashflow(period="all")
        irr = next(x for x in financial["currencies"] if x["currency"] == "IRR")
        self.assertEqual(irr["captured_amount"], "100.00")
        self.assertEqual(irr["refunded_amount"], "50.00")
        self.assertEqual(irr["net_cash_flow"], "50.00")
        reporting = get_reporting_financial(period="month", include_series=True, include_providers=True)
        irr = next(x for x in reporting["currencies"] if x["currency"] == "IRR")
        self.assertEqual(irr["refunded_amount"], "50.00")
        self.assertEqual(sum(Decimal(r["refunded_amount"]) for r in reporting["by_provider"]), Decimal("50.00"))

    def test_unmatured_balance_and_open_returns_block_payout(self):
        order, payment = self.checkout_and_payment()
        payment.mark_success(gateway_reference="manual-test-capture")
        self.assertEqual(payout_eligibility(self.seller.pk, "IRR")["withdrawable_amount"], "0.00")
        now = timezone.now()
        order.status = Order.StatusChoices.DELIVERED
        order.delivered_at = now - timedelta(days=20)
        order.save(update_fields=["status", "delivered_at", "total_amount", "updated_at"])
        fulfillment = SellerOrderFulfillment.objects.get(order=order, seller=self.seller)
        fulfillment.status = Order.StatusChoices.DELIVERED
        fulfillment.save(update_fields=["status", "updated_at"])
        self.assertEqual(payout_eligibility(self.seller.pk, "IRR")["withdrawable_amount"], "90.00")
        ret, _ = self.make_return(order, status_value=ReturnRequest.Status.APPROVED)
        self.assertEqual(payout_eligibility(self.seller.pk, "IRR")["withdrawable_amount"], "0.00")
        ret.status = ReturnRequest.Status.CANCELLED
        ret.save(update_fields=["status", "updated_at"])
        event = {
            "event": "payout.confirmed", "seller_id": self.seller.pk, "currency": "IRR",
            "amount": "40.00", "external_reference": "test-bank-001", "idempotency_key": "test-bank-event-001",
            "confirmed_at": timezone.now().isoformat(),
        }
        response = self.signed_post("settlement-payout-confirmed", event, PAYOUT_SECRET)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.signed_post("settlement-payout-confirmed", event, PAYOUT_SECRET).status_code, 200)
        self.assertEqual(ConfirmedPayout.objects.count(), 1)
        self.assertEqual(seller_balance(self.seller.pk, "IRR"), Decimal("50.00"))
        over = dict(event, amount="60", external_reference="test-bank-002", idempotency_key="test-bank-event-002")
        self.assertEqual(self.signed_post("settlement-payout-confirmed", over, PAYOUT_SECRET).status_code, 409)

    def test_manual_return_cannot_mark_refunded_without_verified_proof(self):
        order, payment = self.checkout_and_payment()
        payment.mark_success(gateway_reference="manual-test-capture")
        ret, item = self.make_return(order, status_value=ReturnRequest.Status.ITEM_RECEIVED)
        from apps.returns.services import mark_return_refunded
        with self.assertRaises(ValidationError):
            mark_return_refunded(return_request=ret, user=self.admin)
        ret.refresh_from_db()
        self.assertEqual(ret.status, ReturnRequest.Status.ITEM_RECEIVED)
