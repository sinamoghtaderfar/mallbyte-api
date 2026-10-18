"""Stage 7 regression tests for scheduled auditing and a purely fake gateway."""

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Seller, User
from apps.inventory.models import Stock, Warehouse
from apps.orders.models import Cart, CartItem, Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.rbac.models import Role
from apps.rbac.utils import assign_role
from apps.returns.models import ReturnItem, ReturnRequest
from apps.settlements.models import ItemAllocation, SellerLedgerEntry
from apps.settlements.monitoring import record_financial_audit
from apps.settlements.monitoring_models import FinancialAuditAlert, FinancialAuditRun
from apps.settlements.services import (
    build_order_allocations,
    post_captured_payment,
    seller_balance,
)
from apps.settlements.tasks import run_daily_financial_audit


@override_settings(
    DEBUG=True,
    SETTLEMENTS_LEDGER_ENABLED=True,
    SETTLEMENTS_DEMO_ENABLED=True,
    SETTLEMENTS_ALLOW_MOCK_SUCCESS=False,
    SETTLEMENTS_PAYOUT_HOLD_DAYS=14,
)
class FinancialMonitoringDemoTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="stage7-admin@example.com", full_name="Admin", password="testpass"
        )
        self.manager = User.objects.create_user(
            email="stage7-manager@example.com", full_name="Manager", password="testpass"
        )
        self.viewer = User.objects.create_user(
            email="stage7-viewer@example.com", full_name="Viewer", password="testpass"
        )
        self.seller = User.objects.create_user(
            email="stage7-seller@example.com",
            full_name="Seller",
            password="testpass",
            is_seller=True,
        )
        self.customer = User.objects.create_user(
            email="stage7-customer@example.com",
            full_name="Customer",
            password="testpass",
        )
        assign_role(self.manager, Role.objects.get(name="analytics_manager"))
        assign_role(self.viewer, Role.objects.get(name="analytics_viewer"))
        assign_role(self.seller, Role.objects.get(name="vendor"))
        Seller.objects.create(
            user=self.seller,
            store_name="Stage7 Store",
            store_slug="stage7-store",
            status=Seller.StatusChoices.APPROVED,
            business_phone="09120000000",
            business_email="stage7-store@example.com",
            commission_rate=Decimal("10"),
        )
        cat = Category.objects.create(name="Stage7 Category", slug="stage7-category")
        self.product = Product.objects.create(
            seller=self.seller,
            category=cat,
            name="Stage7 Product",
            slug="stage7-product",
            sku="STAGE7-SKU",
            price=100,
            status=Product.StatusChoices.APPROVED,
            description="test",
            is_active=True,
        )
        self.warehouse = Warehouse.objects.create(
            name="Stage7 Warehouse",
            code="STAGE7-WH",
            type=Warehouse.TypeChoices.MAIN,
            province="Tehran",
            city="Tehran",
            address="test",
            postal_code="1234567890",
            phone="0210000000",
            manager_name="manager",
            manager_phone="09120000000",
        )
        Stock.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            quantity=20,
            reserved_quantity=0,
        )
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(
            cart=cart, product=self.product, quantity=1, unit_price=Decimal("100")
        )

    def _checkout_and_attempt(self):
        self.client.force_authenticate(user=self.customer)
        created = self.client.post(
            reverse("order-checkout"),
            {
                "receiver_name": "Customer",
                "receiver_phone": "09120000000",
                "province": "Tehran",
                "city": "Tehran",
                "address": "test",
                "postal_code": "1234567890",
                "shipping_cost": "0",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        order = Order.objects.get(pk=created.data["id"])
        self.assertEqual(
            ItemAllocation.objects.filter(order_item__order_id=order.pk).count(), 1
        )
        attempt = self.client.post(
            reverse("payment-list"),
            {"order": order.pk, "provider": "mock"},
            format="json",
        )
        self.assertEqual(attempt.status_code, 201, attempt.data)
        return order, Payment.objects.get(pk=attempt.data["id"])

    def _demo(self, name, payload, user=None):
        self.client.force_authenticate(user=user or self.admin)
        return self.client.post(reverse(name), payload, format="json")

    def _unposted_order(self):
        order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=100,
            receiver_name="Buyer",
            receiver_phone="09120000000",
            province="Tehran",
            city="Tehran",
            address="Test",
            postal_code="1234567890",
        )
        OrderItem.objects.create(
            order=order, product=self.product, quantity=1, unit_price=100
        )
        payment = Payment.objects.create(
            order=order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            amount=100,
            status=Payment.StatusChoices.SUCCESS,
            currency="IRR",
            paid_at=timezone.now(),
        )
        return order, payment

    def test_audit_is_idempotent_per_run_key(self):
        first, created = record_financial_audit(run_key="manual:once", source="manual")
        self.assertTrue(created)
        self.assertEqual(first.status, FinancialAuditRun.Status.CLEAN)
        second, created = record_financial_audit(run_key="manual:once", source="manual")
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(FinancialAuditRun.objects.count(), 1)
        self.assertFalse(FinancialAuditAlert.objects.exists())

    def test_findings_are_deduplicated_and_resolved(self):
        order, payment = self._unposted_order()
        first, _ = record_financial_audit(run_key="manual:warning-1")
        self.assertEqual(first.status, FinancialAuditRun.Status.WARNINGS)
        self.assertTrue(
            FinancialAuditAlert.objects.filter(
                code="captured_items_missing_snapshot", is_open=True
            ).exists()
        )
        second, _ = record_financial_audit(run_key="manual:warning-2")
        self.assertEqual(second.status, FinancialAuditRun.Status.WARNINGS)
        self.assertEqual(
            FinancialAuditAlert.objects.filter(
                code="captured_items_missing_snapshot"
            ).count(),
            1,
        )
        build_order_allocations(order)
        post_captured_payment(payment)
        last, _ = record_financial_audit(run_key="manual:resolved")
        self.assertEqual(last.status, FinancialAuditRun.Status.CLEAN)
        self.assertFalse(FinancialAuditAlert.objects.filter(is_open=True).exists())
        self.assertIsNotNone(
            FinancialAuditAlert.objects.get(
                code="captured_items_missing_snapshot"
            ).resolved_at
        )

    def test_daily_celery_task_replay_uses_single_run(self):
        first = run_daily_financial_audit()
        second = run_daily_financial_audit()
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(FinancialAuditRun.objects.count(), 1)

    def test_audit_failure_is_sanitized_and_recorded(self):
        with patch(
            "apps.settlements.monitoring.reconciliation_report",
            side_effect=RuntimeError("internal secret"),
        ):
            run, created = record_financial_audit(run_key="manual:failure")
        self.assertTrue(created)
        self.assertEqual(run.status, FinancialAuditRun.Status.ERROR)
        self.assertEqual(run.error, "RuntimeError")
        self.assertNotIn("internal secret", run.error)

    def test_monitoring_endpoints_are_role_scoped(self):
        self.client.force_authenticate(user=self.viewer)
        self.assertEqual(
            self.client.get(reverse("settlement-monitoring-runs")).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("settlement-monitoring-alerts")).status_code, 200
        )
        self.assertEqual(
            self.client.post(
                reverse("settlement-monitoring-run-now"), {}, format="json"
            ).status_code,
            403,
        )
        self.client.force_authenticate(user=self.seller)
        self.assertEqual(
            self.client.get(reverse("settlement-monitoring-runs")).status_code, 403
        )
        self.client.force_authenticate(user=self.manager)
        response = self.client.post(
            reverse("settlement-monitoring-run-now"), {}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            self.client.get(
                reverse(
                    "settlement-monitoring-run-detail",
                    args=[response.data["id"]],
                )
            ).status_code,
            200,
        )

    def test_demo_capture_and_replay_post_once(self):
        order, payment = self._checkout_and_attempt()
        endpoint = "settlement-demo-capture"
        first = self._demo(endpoint, {"payment_id": payment.pk})
        self.assertEqual(first.status_code, 200, first.data)
        self.assertTrue(first.data["simulation"])
        self.assertFalse(first.data["replayed"])
        again = self._demo(endpoint, {"payment_id": payment.pk})
        self.assertEqual(again.status_code, 200, again.data)
        self.assertTrue(again.data["replayed"])
        self.assertEqual(seller_balance(self.seller.pk, "IRR"), Decimal("90.00"))
        self.assertEqual(SellerLedgerEntry.objects.filter(kind="sale").count(), 1)

    def test_demo_refund_is_partial_and_replay_safe(self):
        order, payment = self._checkout_and_attempt()
        self.assertEqual(
            self._demo(
                "settlement-demo-capture", {"payment_id": payment.pk}
            ).status_code,
            200,
        )
        ret = ReturnRequest.objects.create(
            order=order,
            customer=self.customer,
            status=ReturnRequest.Status.APPROVED,
            requested_resolution=ReturnRequest.RequestedResolution.REFUND,
            total_requested_amount=50,
            total_approved_amount=50,
        )
        item = order.items.get()
        ReturnItem.objects.create(
            return_request=ret,
            order_item=item,
            quantity=1,
            requested_refund_amount=50,
            approved_refund_amount=50,
            status=ReturnItem.ItemStatus.APPROVED,
        )
        payload = {
            "payment_id": payment.pk,
            "return_request_id": ret.pk,
            "amount": "50.00",
            "currency": "IRR",
            "idempotency_key": "stage7-refund-0001",
            "lines": [
                {
                    "order_item_id": item.pk,
                    "merchandise": "50.00",
                    "shipping": "0",
                    "tax": "0",
                }
            ],
        }
        first = self._demo("settlement-demo-refund", payload)
        self.assertEqual(first.status_code, 200, first.data)
        retry = self._demo("settlement-demo-refund", payload)
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(first.data["refund_id"], retry.data["refund_id"])
        self.assertEqual(seller_balance(self.seller.pk, "IRR"), Decimal("45.00"))
        self.assertEqual(SellerLedgerEntry.objects.filter(kind="refund").count(), 1)

    def test_demo_failure_is_idempotent_and_not_captured(self):
        _, payment = self._checkout_and_attempt()
        payload = {"payment_id": payment.pk, "reason": "Demo declined"}
        self.assertEqual(self._demo("settlement-demo-fail", payload).status_code, 200)
        replay = self._demo("settlement-demo-fail", payload)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.data["replayed"])
        self.assertEqual(
            self._demo(
                "settlement-demo-capture", {"payment_id": payment.pk}
            ).status_code,
            409,
        )
        self.assertFalse(SellerLedgerEntry.objects.exists())

    def test_demo_payout_obeys_hold_policy_and_is_idempotent(self):
        order, payment = self._checkout_and_attempt()
        self.assertEqual(
            self._demo(
                "settlement-demo-capture", {"payment_id": payment.pk}
            ).status_code,
            200,
        )
        payload = {
            "seller_id": self.seller.pk,
            "currency": "IRR",
            "amount": "20.00",
            "idempotency_key": "stage7-payout-0001",
        }
        self.assertEqual(self._demo("settlement-demo-payout", payload).status_code, 409)
        order.status = Order.StatusChoices.DELIVERED
        order.delivered_at = timezone.now() - timedelta(days=20)
        order.save(
            update_fields=["status", "delivered_at", "total_amount", "updated_at"]
        )
        confirmed = self._demo("settlement-demo-payout", payload)
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        repeated = self._demo("settlement-demo-payout", payload)
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(seller_balance(self.seller.pk, "IRR"), Decimal("70.00"))
        self.assertEqual(SellerLedgerEntry.objects.filter(kind="payout").count(), 1)

    def test_demo_is_never_accessible_to_customer_or_in_production(self):
        order, payment = self._checkout_and_attempt()
        payload = {"payment_id": payment.pk}
        self.assertEqual(
            self._demo(
                "settlement-demo-capture", payload, user=self.customer
            ).status_code,
            403,
        )
        with override_settings(DEBUG=False, SETTLEMENTS_DEMO_ENABLED=True):
            self.assertEqual(
                self._demo("settlement-demo-capture", payload).status_code, 403
            )
        with override_settings(DEBUG=True, SETTLEMENTS_DEMO_ENABLED=False):
            self.assertEqual(
                self._demo("settlement-demo-capture", payload).status_code, 403
            )
        self.assertFalse(SellerLedgerEntry.objects.exists())

    @override_settings(
        SETTLEMENTS_CAPTURE_BRIDGE_SECRET="test-a-long-secret-which-is-safe-for-simulation-tests"
    )
    def test_signed_bridge_rejects_tampered_and_expired_requests(self):
        payload = json.dumps({"event": "payment.captured"}).encode("utf-8")
        old_timestamp = str(int((timezone.now() - timedelta(hours=1)).timestamp()))
        secret = "test-a-long-secret-which-is-safe-for-simulation-tests"
        signature = hmac.new(
            secret.encode(), old_timestamp.encode() + b"." + payload, hashlib.sha256
        ).hexdigest()
        self.client.force_authenticate(user=None)
        expired = self.client.post(
            reverse("settlement-capture-confirmed"),
            data=payload,
            content_type="application/json",
            HTTP_X_SETTLEMENT_TIMESTAMP=old_timestamp,
            HTTP_X_SETTLEMENT_SIGNATURE=signature,
        )
        self.assertEqual(expired.status_code, 403)
        current = str(int(timezone.now().timestamp()))
        forged = self.client.post(
            reverse("settlement-capture-confirmed"),
            data=payload,
            content_type="application/json",
            HTTP_X_SETTLEMENT_TIMESTAMP=current,
            HTTP_X_SETTLEMENT_SIGNATURE="0" * 64,
        )
        self.assertEqual(forged.status_code, 403)

    def test_demo_never_accepts_non_mock_provider(self):
        _, payment = self._checkout_and_attempt()
        Payment.objects.filter(pk=payment.pk).update(
            provider=Payment.ProviderChoices.STRIPE
        )
        self.assertEqual(
            self._demo(
                "settlement-demo-capture", {"payment_id": payment.pk}
            ).status_code,
            409,
        )
        self.assertFalse(SellerLedgerEntry.objects.exists())
