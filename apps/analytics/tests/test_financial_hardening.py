"""New targeted regression tests; move to apps/analytics/tests/test_financial_hardening.py."""
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Seller, User
from apps.analytics.seller_services import get_seller_analytics
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.rbac.models import Role
from apps.rbac.utils import assign_role
from apps.returns.models import ReturnRequest
from apps.settlements.models import ConfirmedRefund, RefundAllocation
from apps.settlements.services import build_order_allocations


class FinancialSnapshotAnalyticsTests(APITestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            email="snapshot-seller@example.com", full_name="Seller", password="pass",
            is_seller=True,
        )
        self.customer = User.objects.create_user(
            email="snapshot-buyer@example.com", full_name="Buyer", password="pass",
        )
        Seller.objects.create(
            user=self.seller, store_name="Snapshot Shop", store_slug="snapshot-shop",
            business_phone="09120000000", business_email="shop@example.com",
            status=Seller.StatusChoices.APPROVED, commission_rate=Decimal("10"),
        )
        assign_role(self.seller, Role.objects.get(name="vendor"))
        cat = Category.objects.create(name="Snapshot Test", slug="snapshot-test")
        self.product = Product.objects.create(
            seller=self.seller, category=cat, name="Original Product", slug="original-snapshot",
            sku="SNAP-SKU", description="Test", price=100,
            status=Product.StatusChoices.APPROVED,
        )
        self.order = Order.objects.create(
            user=self.customer, status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID, subtotal=100,
            receiver_name="Buyer", receiver_phone="09120000000",
            province="Tehran", city="Tehran", address="Test", postal_code="1234567890",
        )
        self.item = OrderItem.objects.create(
            order=self.order, product=self.product, quantity=1, unit_price=Decimal("100"),
            product_name="Original Product", product_sku="SNAP-SKU",
        )
        self.allocation = build_order_allocations(self.order)[0]
        self.payment = Payment.objects.create(
            order=self.order, user=self.customer, provider=Payment.ProviderChoices.MOCK,
            amount=100, status=Payment.StatusChoices.SUCCESS, currency="IRR",
            paid_at=timezone.now(),
        )

    def test_snapshot_ownership_does_not_change_with_product_owner(self):
        other = User.objects.create_user(
            email="other@example.com", full_name="Other", password="pass", is_seller=True,
        )
        Product.objects.filter(pk=self.product.pk).update(seller_id=other.pk)
        report = get_seller_analytics(seller_id=self.seller.pk, period="month")
        self.assertEqual(report["currencies"][0]["gross_merchandise_value"], "100.00")
        self.assertEqual(report["currencies"][0]["net_merchandise_value"], "100.00")

    def test_partial_refund_is_counted_even_when_payment_remains_success(self):
        ret = ReturnRequest.objects.create(
            order=self.order, customer=self.customer,
            status=ReturnRequest.Status.APPROVED,
            total_requested_amount=30, total_approved_amount=30,
        )
        refund = ConfirmedRefund.objects.create(
            payment=self.payment, return_request=ret, gateway_reference="SNAP-REF-1",
            idempotency_key="snapshot-refund-1", currency="IRR", amount=30,
            confirmed_at=timezone.now(),
        )
        RefundAllocation.objects.create(
            refund=refund, allocation=self.allocation,
            customer_amount=30, customer_merchandise=30,
            customer_shipping=0, customer_tax=0,
            seller_reversal=27, commission_reversal=3,
        )
        report = get_seller_analytics(seller_id=self.seller.pk, period="month")
        currency = report["currencies"][0]
        self.assertEqual(currency["refunded_merchandise_value"], "30.00")
        self.assertEqual(currency["net_merchandise_value"], "70.00")
        self.assertTrue(report["accounting_notes"]["partial_refunds_supported"])
        series = get_seller_analytics(seller_id=self.seller.pk, period="month", dimension="timeseries")
        self.assertEqual(
            sum(Decimal(point["refunded_merchandise_value"]) for point in series["series"][0]["points"]),
            Decimal("30.00"),
        )

    def test_async_manual_audit_queues_instead_of_running_request(self):
        manager = User.objects.create_user(
            email="snapshot-manager@example.com", full_name="Manager", password="pass",
        )
        assign_role(manager, Role.objects.get(name="analytics_manager"))
        self.client.force_authenticate(user=manager)
        with patch("apps.settlements.monitoring_views.run_manual_financial_audit.delay") as delay:
            delay.return_value.id = "celery-test-task"
            response = self.client.post(reverse("settlement-monitoring-run-now"), {}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        self.assertTrue(response.data["queued"])
        self.assertEqual(response.data["task_id"], "celery-test-task")
        self.assertFalse(response.data.get("id"))
