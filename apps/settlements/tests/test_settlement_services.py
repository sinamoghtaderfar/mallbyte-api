from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Seller, User
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.returns.models import ReturnRequest, ReturnItem
from apps.rbac.models import Role
from apps.rbac.utils import assign_role
from apps.settlements.models import ItemAllocation, SellerLedgerEntry, ConfirmedRefund
from apps.settlements.services import (
    allocate, build_order_allocations, post_captured_payment,
    post_verified_refund, post_confirmed_payout, seller_balance,
)


class SettlementAccountingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="sett-admin@example.com", password="test", full_name="Admin", is_superuser=True)
        self.seller_a = User.objects.create_user(email="sett-a@example.com", password="test", full_name="Seller A", is_seller=True)
        self.seller_b = User.objects.create_user(email="sett-b@example.com", password="test", full_name="Seller B", is_seller=True)
        self.customer = User.objects.create_user(email="sett-c@example.com", password="test", full_name="Customer")
        Seller.objects.create(user=self.seller_a, store_name="Settlement Shop A", store_slug="settlement-shop-a", status=Seller.StatusChoices.APPROVED, business_phone="09120111111", business_email="shop-a@example.com", commission_rate=Decimal("10"))
        Seller.objects.create(user=self.seller_b, store_name="Settlement Shop B", store_slug="settlement-shop-b", status=Seller.StatusChoices.APPROVED, business_phone="09120222222", business_email="shop-b@example.com", commission_rate=Decimal("20"))
        cat = Category.objects.create(name="Settlement Test", slug="settlement-test")
        self.product_a = Product.objects.create(seller=self.seller_a, category=cat, name="A", slug="settlement-product-a", description="x", price=100, sku="sett-a-sku", status=Product.StatusChoices.APPROVED)
        self.product_b = Product.objects.create(seller=self.seller_b, category=cat, name="B", slug="settlement-product-b", description="x", price=200, sku="sett-b-sku", status=Product.StatusChoices.APPROVED)
        self.order = Order.objects.create(
            user=self.customer, status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=300, discount_amount=30, shipping_cost=20, tax_amount=10,
            receiver_name="Customer", receiver_phone="09129999999", province="Tehran",
            city="Tehran", address="Test address", postal_code="1234567890",
        )
        self.item_a = OrderItem.objects.create(order=self.order, product=self.product_a, product_name="A", product_sku="A", quantity=1, unit_price=100)
        self.item_b = OrderItem.objects.create(order=self.order, product=self.product_b, product_name="B", product_sku="B", quantity=1, unit_price=200)
        self.now = timezone.now()
        self.payment = Payment.objects.create(
            order=self.order, user=self.customer, provider=Payment.ProviderChoices.MOCK,
            status=Payment.StatusChoices.SUCCESS, amount=300, currency="IRR",
            paid_at=self.now, created_by=self.admin,
        )

    def _snap_and_post(self):
        snaps = build_order_allocations(self.order)
        post_captured_payment(self.payment)
        return snaps

    def test_largest_remainder_is_exact(self):
        self.assertEqual(allocate("0.02", [1, 1, 1]), [Decimal("0.01"), Decimal("0.01"), Decimal("0.00")])

    def test_snapshot_reconciles_and_captures_original_ownership(self):
        rows = self._snap_and_post()
        self.assertEqual(sum((x.discount for x in rows), Decimal(0)), Decimal("30.00"))
        self.assertEqual(sum((x.shipping for x in rows), Decimal(0)), Decimal("20.00"))
        self.assertEqual(sum((x.tax for x in rows), Decimal(0)), Decimal("10.00"))
        self.assertEqual(sum((x.charged for x in rows), Decimal(0)), Decimal("300.00"))
        a = ItemAllocation.objects.get(order_item=self.item_a)
        b = ItemAllocation.objects.get(order_item=self.item_b)
        self.assertEqual((a.merchandise_net, a.commission, a.seller_payable), (Decimal("90.00"), Decimal("9.00"), Decimal("81.00")))
        self.assertEqual((b.merchandise_net, b.commission, b.seller_payable), (Decimal("180.00"), Decimal("36.00"), Decimal("144.00")))
        self.assertEqual(seller_balance(self.seller_a.pk, "IRR"), Decimal("81.00"))
        self.assertEqual(seller_balance(self.seller_b.pk, "IRR"), Decimal("144.00"))
        post_captured_payment(self.payment)
        self.assertEqual(SellerLedgerEntry.objects.filter(kind="sale").count(), 2)
        # Ownership is frozen at order capture.
        self.product_a.seller = self.seller_b
        self.product_a.save(update_fields=["seller"])
        self.assertEqual(ItemAllocation.objects.get(order_item=self.item_a).seller_id, self.seller_a.pk)

    def test_approved_partial_refund_reverses_only_seller_a_and_is_idempotent(self):
        self._snap_and_post()
        ret = ReturnRequest.objects.create(
            customer=self.customer, order=self.order, status=ReturnRequest.Status.APPROVED,
            reason=ReturnRequest.Reason.DAMAGED,
            requested_resolution=ReturnRequest.RequestedResolution.REFUND,
            total_requested_amount=50, total_approved_amount=50,
        )
        ReturnItem.objects.create(
            return_request=ret, order_item=self.item_a, quantity=1,
            requested_refund_amount=50, approved_refund_amount=50,
            status=ReturnItem.ItemStatus.APPROVED,
        )
        kwargs = dict(
            payment_id=self.payment.pk, return_request_id=ret.pk, confirmed_amount="50.00",
            currency="IRR", gateway_reference="gateway-ref-001", idempotency_key="refund-001",
            lines=[{"order_item_id": self.item_a.pk, "merchandise": "50.00", "shipping": "0", "tax": "0"}], confirmed_at=self.now,
        )
        first = post_verified_refund(**kwargs)
        second = post_verified_refund(**kwargs)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ConfirmedRefund.objects.count(), 1)
        self.assertEqual(seller_balance(self.seller_a.pk, "IRR"), Decimal("36.00"))
        self.assertEqual(seller_balance(self.seller_b.pk, "IRR"), Decimal("144.00"))
        with self.assertRaises(ValidationError):
            post_verified_refund(**{**kwargs, "idempotency_key": "refund-002", "gateway_reference": "gateway-ref-002"})
        self.assertEqual(self.payment.status, Payment.StatusChoices.SUCCESS)

    def test_over_refund_is_blocked(self):
        self._snap_and_post()
        ret = ReturnRequest.objects.create(
            customer=self.customer, order=self.order, status=ReturnRequest.Status.APPROVED,
            requested_resolution=ReturnRequest.RequestedResolution.REFUND,
            total_requested_amount=200, total_approved_amount=200,
        )
        ReturnItem.objects.create(return_request=ret, order_item=self.item_a, quantity=1,
                                  requested_refund_amount=200, approved_refund_amount=200)
        with self.assertRaises(ValidationError):
            post_verified_refund(payment_id=self.payment.pk, return_request_id=ret.pk,
                confirmed_amount="200", currency="IRR", gateway_reference="badref", idempotency_key="bad1",
                lines=[{"order_item_id": self.item_a.pk, "merchandise": "200", "shipping": "0", "tax": "0"}], confirmed_at=self.now)
        self.assertEqual(ConfirmedRefund.objects.count(), 0)

    def test_confirmed_payout_never_initiates_transfer_and_is_idempotent(self):
        self._snap_and_post()
        args = dict(seller_id=self.seller_a.pk, currency="IRR", amount="40", external_reference="bank-001", idempotency_key="pay-001", confirmed_at=self.now)
        first = post_confirmed_payout(**args)
        self.assertEqual(first.pk, post_confirmed_payout(**args).pk)
        self.assertEqual(seller_balance(self.seller_a.pk, "IRR"), Decimal("41.00"))
        self.assertEqual(SellerLedgerEntry.objects.filter(kind="payout").count(), 1)
        with self.assertRaises(ValidationError):
            post_confirmed_payout(**{**args, "external_reference": "bank-002", "idempotency_key": "pay-002", "amount": "42"})

    def test_seller_statement_and_csv_are_scoped(self):
        self._snap_and_post()
        vendor = Role.objects.get(name="vendor")
        assign_role(self.seller_a, vendor)
        api = APIClient()
        api.force_authenticate(self.seller_a)
        detail = api.get(reverse("seller-financial-statement"), {"seller_id": self.seller_b.pk})
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["currencies"][0]["balance"], "81.00")
        csv_res = api.get(reverse("seller-financial-export"), {"seller_id": self.seller_b.pk})
        self.assertEqual(csv_res.status_code, 200)
        self.assertNotIn(b"144.00", b"".join(csv_res.streaming_content))
