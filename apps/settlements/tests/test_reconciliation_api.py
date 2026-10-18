import csv
import io
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Seller, User
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.rbac.models import Role
from apps.rbac.utils import assign_role
from apps.settlements.models import (
    ConfirmedPayout,
    SellerLedgerEntry,
)
from apps.settlements.services import (
    build_order_allocations,
    post_captured_payment,
)


class ReconciliationAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="stage6-admin@example.com",
            full_name="Admin",
            password="test",
            is_superuser=True,
            is_staff=True,
        )

        self.viewer = User.objects.create_user(
            email="stage6-viewer@example.com",
            full_name="Viewer",
            password="test",
        )

        self.manager = User.objects.create_user(
            email="stage6-manager@example.com",
            full_name="Manager",
            password="test",
        )

        self.seller = User.objects.create_user(
            email="stage6-seller@example.com",
            full_name="Seller",
            password="test",
            is_seller=True,
        )

        self.customer = User.objects.create_user(
            email="stage6-buyer@example.com",
            full_name="Customer",
            password="test",
        )

        assign_role(
            self.viewer,
            Role.objects.get(name="analytics_viewer"),
        )

        assign_role(
            self.manager,
            Role.objects.get(name="analytics_manager"),
        )

        assign_role(
            self.seller,
            Role.objects.get(name="vendor"),
        )

        Seller.objects.create(
            user=self.seller,
            store_name="Stage6 Shop",
            store_slug="stage6-shop",
            status=Seller.StatusChoices.APPROVED,
            business_phone="09123456789",
            business_email="stage6-shop@example.com",
            commission_rate=Decimal("10.00"),
        )

        self.category = Category.objects.create(
            name="Stage6 Category",
            slug="stage6-category",
        )

        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Stage6 Product",
            slug="stage6-product",
            sku="STAGE6-SKU",
            price=100,
            description="Integration test",
            status=Product.StatusChoices.APPROVED,
        )

        self.order = self._make_order(1)
        self.payment = self._make_payment(self.order)

        self.allocation = build_order_allocations(self.order)[0]

        post_captured_payment(self.payment)

    def _make_order(self, number):
        order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("100"),
            receiver_name="Buyer",
            receiver_phone="09120000000",
            province="Tehran",
            city="Tehran",
            address="Example",
            postal_code="1234567890",
        )

        OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            unit_price=Decimal("100"),
            product_name=f"Item {number}",
            product_sku=self.product.sku,
        )

        return order

    def _make_payment(self, order):
        return Payment.objects.create(
            order=order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status=Payment.StatusChoices.SUCCESS,
            amount=Decimal("100"),
            currency="IRR",
            paid_at=timezone.now(),
        )

    def _get(self, user, url_name, data=None):
        self.client.force_authenticate(user=user)

        return self.client.get(
            reverse(url_name),
            data or {},
        )

    def test_consistent_capture_has_no_detected_findings(self):
        response = self._get(
            self.admin,
            "settlement-reconciliation",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["total_findings"],
            0,
        )
        self.assertEqual(
            response.data["status"],
            "no_detected_mismatches",
        )

    def test_missing_snapshot_for_captured_payment_is_reported(self):
        order = self._make_order(2)
        self._make_payment(order)

        response = self._get(
            self.admin,
            "settlement-reconciliation",
        )

        finding = response.data["findings"]["captured_items_missing_snapshot"]

        self.assertEqual(finding["count"], 1)
        self.assertEqual(
            len(finding["sample_ids"]),
            1,
        )

    def test_duplicate_sale_and_missing_payout_debit_are_reported(self):
        SellerLedgerEntry.objects.create(
            seller=self.seller,
            currency="IRR",
            kind=SellerLedgerEntry.Kind.SALE,
            source_key="test:extra-sale",
            allocation=self.allocation,
            amount=Decimal("90.00"),
            occurred_at=timezone.now(),
        )

        ConfirmedPayout.objects.create(
            seller=self.seller,
            currency="IRR",
            amount=Decimal("20.00"),
            external_reference="stage6-external-bank-ref",
            idempotency_key="stage6-payout-key",
            confirmed_at=timezone.now(),
        )

        response = self._get(
            self.admin,
            "settlement-reconciliation",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        findings = response.data["findings"]

        self.assertEqual(
            findings["duplicate_sale_credits_per_allocation"]["count"],
            1,
        )

        self.assertEqual(
            findings["payout_missing_or_incorrect_seller_debit"]["count"],
            1,
        )

    def test_balance_report_is_paginated_and_scoped_to_admin(self):
        response = self._get(
            self.viewer,
            "settlement-admin-balances",
            {
                "seller_id": self.seller.id,
                "currency": "irr",
                "page_size": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        self.assertEqual(
            response.data["results"][0]["balance"],
            "90.00",
        )

        self.assertEqual(
            response.data["results"][0]["currency"],
            "IRR",
        )

        invalid_response = self._get(
            self.viewer,
            "settlement-admin-balances",
            {"page_size": 0},
        )

        self.assertEqual(
            invalid_response.status_code,
            400,
        )

    def test_viewer_can_read_but_cannot_export(self):
        self.assertEqual(
            self._get(
                self.viewer,
                "settlement-reconciliation",
            ).status_code,
            200,
        )

        self.assertEqual(
            self._get(
                self.viewer,
                "settlement-reconciliation-export",
            ).status_code,
            403,
        )

        self.assertEqual(
            self._get(
                self.viewer,
                "settlement-admin-balances-export",
            ).status_code,
            403,
        )

    def test_seller_is_not_allowed_platform_reconciliation(self):
        for endpoint in (
            "settlement-reconciliation",
            "settlement-reconciliation-export",
            "settlement-admin-balances",
            "settlement-admin-balances-export",
        ):
            self.assertEqual(
                self._get(
                    self.seller,
                    endpoint,
                ).status_code,
                403,
            )

        self.client.force_authenticate(user=None)

        response = self.client.get(reverse("settlement-reconciliation"))

        self.assertIn(
            response.status_code,
            (401, 403),
        )

    def test_manager_export_and_no_ledger_mutation(self):
        before = SellerLedgerEntry.objects.count()

        response = self._get(
            self.manager,
            "settlement-admin-balances-export",
        )

        self.assertEqual(response.status_code, 200)

        content = b"".join(response.streaming_content).decode("utf-8-sig")

        rows = list(csv.DictReader(io.StringIO(content)))

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["balance"],
            "90.00",
        )

        audit = self._get(
            self.manager,
            "settlement-reconciliation-export",
        )

        self.assertEqual(audit.status_code, 200)

        self.assertIn(
            "check,count,sample_ids,generated_at",
            b"".join(audit.streaming_content).decode("utf-8-sig"),
        )

        self.assertEqual(
            SellerLedgerEntry.objects.count(),
            before,
        )
