from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Seller, User
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.rbac.models import Role
from apps.rbac.utils import assign_role, remove_role


class SellerAnalyticsAPITests(APITestCase):
    def _user(self, idx, *, seller=False, staff=False):
        return User.objects.create_user(
            email=f"seller-analytics-{idx}@example.com",
            full_name=f"User {idx}",
            password="testpass123",
            phone=f"+989971991{idx:04d}",
            is_seller=seller,
            is_staff=staff,
        )

    def _seller(self, user, idx, status_value=Seller.StatusChoices.APPROVED):
        return Seller.objects.create(
            user=user,
            store_name=f"Analytics Store {idx}",
            store_slug=f"analytics-store-{idx}",
            status=status_value,
            business_phone=f"0912000{idx:04d}",
            business_email=f"store-{idx}@example.com",
        )

    def _product(self, seller, idx):
        return Product.objects.create(
            seller=seller,
            category=self.category,
            name=f"Product {idx}",
            slug=f"seller-product-{idx}",
            description="test",
            price=100,
            sku=f"SELLER-ANALYTICS-{idx}",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

    def _order(
        self,
        items,
        *,
        payment_status=Payment.StatusChoices.SUCCESS,
        paid_at=None,
        refunded_at=None,
        currency="IRR",
    ):
        total = sum((Decimal(str(price)) for _, price in items), Decimal("0"))
        order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=total,
            receiver_name="Customer",
            receiver_phone="09120000000",
            province="Tehran",
            city="Tehran",
            address="Test address",
            postal_code="1234567890",
        )
        for product, price in items:
            OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                product_sku=product.sku,
                quantity=1,
                unit_price=Decimal(str(price)),
            )
        Payment.objects.create(
            order=order,
            user=self.customer,
            status=payment_status,
            provider=Payment.ProviderChoices.MOCK,
            amount=total,
            currency=currency,
            paid_at=paid_at,
            refunded_at=refunded_at,
        )
        return order

    def setUp(self):
        self.a = self._user(1, seller=True)
        self.b = self._user(2, seller=True)
        self.customer = self._user(3)
        self.staff = self._user(4, staff=True)
        self.pending = self._user(5, seller=True)
        self._seller(self.a, 1)
        self._seller(self.b, 2)
        self._seller(self.pending, 3, Seller.StatusChoices.PENDING)
        vendor = Role.objects.get(name="vendor")
        for user in (self.a, self.b, self.pending):
            assign_role(user, vendor)
        self.category = Category.objects.create(
            name="Seller Analytics Category", slug="seller-analytics-category"
        )
        self.p_a = self._product(self.a, 1)
        self.p_b = self._product(self.b, 2)
        now = timezone.now()
        self._order([(self.p_a, 100), (self.p_b, 200)], paid_at=now)
        self._order(
            [(self.p_a, 80), (self.p_b, 120)],
            paid_at=now - timedelta(days=2),
            refunded_at=now,
            payment_status=Payment.StatusChoices.REFUNDED,
        )
        self._order([(self.p_b, 700)], paid_at=now)
        self.urls = (
            "analytics-seller-dashboard",
            "analytics-seller-timeseries",
            "analytics-seller-products",
        )

    def _call(self, user, endpoint, params=None):
        self.client.force_authenticate(user=user)
        return self.client.get(reverse(endpoint), params or {"period": "month"})

    def test_multiseller_order_never_exposes_others_amounts(self):
        a = self._call(self.a, "analytics-seller-dashboard")
        b = self._call(self.b, "analytics-seller-dashboard")
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(a.data["currencies"][0]["gross_merchandise_value"], "180.00")
        self.assertEqual(
            a.data["currencies"][0]["fully_refunded_merchandise_value"], "80.00"
        )
        self.assertEqual(a.data["currencies"][0]["net_merchandise_value"], "100.00")
        self.assertEqual(b.data["currencies"][0]["gross_merchandise_value"], "1020.00")
        self.assertEqual(b.data["currencies"][0]["net_merchandise_value"], "900.00")
        self.assertEqual(a.data["catalog"]["total_products"], 1)

    def test_seller_id_query_parameter_cannot_switch_scope(self):
        response = self._call(
            self.a, "analytics-seller-products", {"seller_id": self.b.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["scope"]["seller_id"], self.a.id)
        groups = response.data["products_by_currency"]
        ids = {row["product_id"] for g in groups for row in g["products"]}
        self.assertEqual(ids, {self.p_a.id})
        self.assertNotIn(self.p_b.name, str(groups))

    def test_timeseries_reconciles_with_dashboard(self):
        response = self._call(self.a, "analytics-seller-timeseries")
        self.assertEqual(response.status_code, 200)
        currency = response.data["currencies"][0]
        series = response.data["series"][0]["points"]
        for field in (
            "gross_merchandise_value",
            "fully_refunded_merchandise_value",
            "net_merchandise_value",
        ):
            self.assertEqual(
                sum(Decimal(point[field]) for point in series),
                Decimal(currency[field]),
            )

    def test_refund_on_current_date_reverses_prior_capture(self):
        response = self._call(self.a, "analytics-seller-dashboard", {"period": "today"})
        item = response.data["currencies"][0]
        self.assertEqual(item["gross_merchandise_value"], "100.00")
        self.assertEqual(item["fully_refunded_merchandise_value"], "80.00")
        self.assertEqual(item["net_merchandise_value"], "20.00")

    def test_seller_without_vendor_role_is_denied(self):
        remove_role(self.a, Role.objects.get(name="vendor"))
        self.assertEqual(
            self._call(self.a, "analytics-seller-dashboard").status_code, 403
        )

    def test_suspended_seller_is_denied(self):
        Seller.objects.filter(user=self.a).update(status=Seller.StatusChoices.SUSPENDED)
        for endpoint in self.urls:
            self.assertEqual(self._call(self.a, endpoint).status_code, 403)

    def test_pending_seller_is_denied(self):
        self.assertEqual(
            self._call(self.pending, "analytics-seller-dashboard").status_code,
            403,
        )

    def test_staff_customer_and_anonymous_denied(self):
        for user in (self.staff, self.customer):
            for endpoint in self.urls:
                self.assertEqual(self._call(user, endpoint).status_code, 403)
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("analytics-seller-dashboard"))
        self.assertIn(response.status_code, (401, 403))

    def test_all_period_rejected_for_timeseries(self):
        self.assertEqual(
            self._call(
                self.a, "analytics-seller-timeseries", {"period": "all"}
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_oversized_custom_timeseries_is_rejected(self):
        self.assertEqual(
            self._call(
                self.a,
                "analytics-seller-timeseries",
                {"start_date": "2020-01-01", "end_date": "2026-01-01"},
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_failed_payment_is_not_counted(self):
        self._order(
            [(self.p_a, 900)],
            payment_status=Payment.StatusChoices.FAILED,
            paid_at=None,
        )
        response = self._call(self.a, "analytics-seller-dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["currencies"][0]["gross_merchandise_value"],
            "180.00",
        )

    def test_currencies_never_get_aggregated_together(self):
        self._order([(self.p_a, 50)], paid_at=timezone.now(), currency="usd")
        response = self._call(self.a, "analytics-seller-dashboard")
        amounts = {
            item["currency"]: item["gross_merchandise_value"]
            for item in response.data["currencies"]
        }
        self.assertEqual(amounts, {"IRR": "180.00", "USD": "50.00"})

    def test_custom_dates_must_be_complete_and_ordered(self):
        for params in (
            {"start_date": "2026-10-01"},
            {"start_date": "2026-10-18", "end_date": "2026-10-01"},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    self._call(
                        self.a, "analytics-seller-dashboard", params
                    ).status_code,
                    status.HTTP_400_BAD_REQUEST,
                )

    def test_superuser_without_approved_seller_profile_cannot_impersonate(self):
        superuser = self._user(6, staff=True)
        superuser.is_superuser = True
        superuser.save(update_fields=["is_superuser"])
        self.assertEqual(
            self._call(superuser, "analytics-seller-dashboard").status_code,
            status.HTTP_403_FORBIDDEN,
        )
