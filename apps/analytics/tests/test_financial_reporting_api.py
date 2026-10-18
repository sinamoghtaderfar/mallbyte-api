from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.rbac.models import Role
from apps.rbac.utils import assign_role


class FinancialReportingIntegrationTests(APITestCase):
    def setUp(self):
        self.admin = self._user(
            "+989971001001",
            "integration-admin@example.com",
            is_superuser=True,
        )
        self.viewer = self._user(
            "+989971001002",
            "integration-viewer@example.com",
        )
        self.customer = self._user(
            "+989971001003",
            "integration-customer@example.com",
        )

        assign_role(
            self.viewer,
            Role.objects.get(name="analytics_viewer"),
        )

        self.endpoints = (
            "analytics-dashboard",
            "analytics-timeseries",
            "analytics-breakdown",
        )

        self.client.force_authenticate(user=self.admin)

    @staticmethod
    def _user(phone, email, *, is_superuser=False):
        user = User(
            phone=phone,
            email=email,
            full_name=email.split("@")[0],
            is_active=True,
            is_staff=False,
            is_superuser=is_superuser,
        )
        user.set_password("testpass123")
        user.save()
        return user

    def _payment(
        self,
        *,
        amount,
        status_value="success",
        currency="IRR",
        provider="mock",
        paid_at=None,
        refunded_at=None,
    ):
        order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal(str(amount)),
            receiver_name="Customer",
            receiver_phone="09120000000",
            province="Tehran",
            city="Tehran",
            address="Test address",
            postal_code="1234567890",
        )

        return Payment.objects.create(
            order=order,
            user=self.customer,
            provider=provider,
            status=status_value,
            amount=Decimal(str(amount)),
            currency=currency,
            paid_at=paid_at,
            refunded_at=refunded_at,
            created_by=self.admin,
        )

    def _get_all(self, params=None):
        output = {}

        for endpoint in self.endpoints:
            response = self.client.get(
                reverse(endpoint),
                data=params or {"period": "month"},
            )

            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
                endpoint,
            )
            self.assertIn("financial", response.data)

            output[endpoint] = response.data["financial"]

        return output

    @staticmethod
    def _currency(financial, currency):
        return next(
            row for row in financial["currencies"] if row["currency"] == currency
        )

    def test_canonical_currency_totals_are_identical_across_three_apis(
        self,
    ):
        now = timezone.now()

        self._payment(
            amount="500",
            paid_at=now,
            currency="IRR",
        )

        self._payment(
            amount="40",
            paid_at=now,
            currency="usd",
            provider="stripe",
        )

        self._payment(
            amount="100",
            paid_at=now - timedelta(days=2),
            refunded_at=now,
            status_value=Payment.StatusChoices.REFUNDED,
        )

        responses = self._get_all(
            {
                "start_date": (timezone.localdate() - timedelta(days=7)).isoformat(),
                "end_date": timezone.localdate().isoformat(),
            }
        )

        dashboard = responses["analytics-dashboard"]

        for data in responses.values():
            self.assertEqual(
                data["currencies"],
                dashboard["currencies"],
            )
            self.assertEqual(
                data["metric_contract_version"],
                1,
            )
            self.assertEqual(
                data["filters"],
                dashboard["filters"],
            )

        irr = self._currency(dashboard, "IRR")
        usd = self._currency(dashboard, "USD")

        self.assertEqual(irr["captured_amount"], "600.00")
        self.assertEqual(irr["refunded_amount"], "100.00")
        self.assertEqual(irr["net_cash_flow"], "500.00")
        self.assertEqual(usd["captured_amount"], "40.00")
        self.assertEqual(usd["net_cash_flow"], "40.00")

        self.assertNotIn(
            "net_cash_flow",
            dashboard,
        )

    def test_timeseries_daily_sum_matches_cashflow_summary(
        self,
    ):
        now = timezone.now()

        self._payment(
            amount="200",
            paid_at=now - timedelta(days=3),
            refunded_at=now,
            status_value=Payment.StatusChoices.REFUNDED,
        )

        self._payment(
            amount="80",
            paid_at=now,
        )

        response = self.client.get(
            reverse("analytics-timeseries"),
            {"period": "month"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        financial = response.data["financial"]
        irr = self._currency(financial, "IRR")

        series = next(row for row in financial["series"] if row["currency"] == "IRR")

        for field in (
            "captured_amount",
            "refunded_amount",
            "net_cash_flow",
        ):
            self.assertEqual(
                sum(Decimal(point[field]) for point in series["points"]),
                Decimal(irr[field]),
            )

        today = timezone.localdate().isoformat()

        today_point = next(
            point for point in series["points"] if point["date"] == today
        )

        self.assertEqual(
            today_point["refunded_amount"],
            "200.00",
        )
        self.assertEqual(
            today_point["net_cash_flow"],
            "-120.00",
        )

    def test_provider_breakdown_reconciles_by_currency(
        self,
    ):
        now = timezone.now()

        self._payment(
            amount="125",
            paid_at=now,
            provider="mock",
        )

        self._payment(
            amount="50",
            paid_at=now - timedelta(days=1),
            refunded_at=now,
            provider="stripe",
            status_value=Payment.StatusChoices.REFUNDED,
        )

        response = self.client.get(
            reverse("analytics-breakdown"),
            {"period": "month"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        financial = response.data["financial"]
        irr = self._currency(financial, "IRR")

        providers = [
            row for row in financial["by_provider"] if row["currency"] == "IRR"
        ]

        self.assertEqual(
            {row["provider"] for row in providers},
            {"mock", "stripe"},
        )

        for field in (
            "captured_amount",
            "refunded_amount",
            "net_cash_flow",
        ):
            self.assertEqual(
                sum(Decimal(row[field]) for row in providers),
                Decimal(irr[field]),
            )

    def test_paid_at_not_payment_creation_date(self):
        payment = self._payment(
            amount="60",
            paid_at=timezone.now(),
        )

        Payment.objects.filter(pk=payment.pk).update(
            created_at=timezone.now() - timedelta(days=120),
        )

        responses = self._get_all({"period": "today"})

        for financial in responses.values():
            self.assertEqual(
                self._currency(financial, "IRR")["captured_amount"],
                "60.00",
            )

    def test_custom_range_counts_refund_even_when_capture_was_earlier(
        self,
    ):
        now = timezone.now()

        self._payment(
            amount="70",
            paid_at=now - timedelta(days=5),
            refunded_at=now,
            status_value=Payment.StatusChoices.REFUNDED,
        )

        today = timezone.localdate().isoformat()

        responses = self._get_all(
            {
                "start_date": today,
                "end_date": today,
            }
        )

        for financial in responses.values():
            irr = self._currency(financial, "IRR")

            self.assertEqual(irr["captured_amount"], "0.00")
            self.assertEqual(irr["refunded_amount"], "70.00")
            self.assertEqual(irr["net_cash_flow"], "-70.00")

    def test_legacy_response_fields_remain_available(self):
        data = {}

        for name in self.endpoints:
            response = self.client.get(reverse(name))
            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
            )
            data[name] = response.data

        self.assertIn("sales", data["analytics-dashboard"])
        self.assertIn("trends", data["analytics-dashboard"])
        self.assertIn("points", data["analytics-timeseries"])
        self.assertIn("totals", data["analytics-timeseries"])
        self.assertIn(
            "revenue_by_category",
            data["analytics-breakdown"],
        )
        self.assertIn(
            "top_selling_products",
            data["analytics-breakdown"],
        )

    def test_viewer_allowed_and_customer_denied(self):
        self.client.force_authenticate(user=self.viewer)

        for name in self.endpoints:
            response = self.client.get(reverse(name))

            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
            )

        self.client.force_authenticate(user=self.customer)

        for name in self.endpoints:
            response = self.client.get(reverse(name))

            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
            )
