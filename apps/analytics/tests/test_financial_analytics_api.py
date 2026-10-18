from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.analytics.financial import get_financial_window
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.rbac.models import Role
from apps.rbac.utils import assign_role


class FinancialAnalyticsAPITests(APITestCase):
    def create_user(
        self,
        *,
        phone,
        email,
        is_staff=False,
        is_seller=False,
        is_superuser=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=email.split("@")[0],
            is_active=True,
            is_staff=is_staff,
            is_seller=is_seller,
            is_superuser=is_superuser,
        )
        user.set_password("testpass123")
        user.save()
        return user

    def setUp(self):
        self.superuser = self.create_user(
            phone="+989960000001",
            email="finance-admin@example.com",
            is_superuser=True,
        )

        self.viewer = self.create_user(
            phone="+989960000002",
            email="finance-viewer@example.com",
        )
        assign_role(
            self.viewer,
            Role.objects.get(name="analytics_viewer"),
        )

        self.regular_staff = self.create_user(
            phone="+989960000003",
            email="finance-staff@example.com",
            is_staff=True,
        )

        self.seller = self.create_user(
            phone="+989960000004",
            email="finance-seller@example.com",
            is_seller=True,
        )

        self.customer = self.create_user(
            phone="+989960000005",
            email="finance-customer@example.com",
        )

        self.url = reverse("analytics-financial")

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_payment(
        self,
        *,
        amount,
        currency="IRR",
        payment_status=Payment.StatusChoices.SUCCESS,
        paid_at=None,
        refunded_at=None,
    ):
        amount = Decimal(str(amount))

        order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=amount,
            receiver_name="Finance Customer",
            receiver_phone="09120000000",
            province="Tehran",
            city="Tehran",
            address="Finance test address",
            postal_code="1234567890",
        )

        return Payment.objects.create(
            order=order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status=payment_status,
            amount=amount,
            currency=currency,
            paid_at=paid_at,
            refunded_at=refunded_at,
            created_by=self.superuser,
        )

    def get_currency(self, response, currency):
        return next(
            item for item in response.data["currencies"] if item["currency"] == currency
        )

    def test_successful_payment_uses_paid_at(self):
        self.authenticate(self.superuser)

        yesterday = timezone.now() - timedelta(days=1)

        self.create_payment(
            amount="100000",
            paid_at=yesterday,
        )

        today_response = self.client.get(
            self.url,
            {"period": "today"},
        )

        self.assertEqual(
            today_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            today_response.data["currencies"],
            [],
        )

        yesterday_date = timezone.localdate(yesterday)

        yesterday_response = self.client.get(
            self.url,
            {
                "start_date": yesterday_date.isoformat(),
                "end_date": yesterday_date.isoformat(),
            },
        )

        self.assertEqual(
            yesterday_response.status_code,
            status.HTTP_200_OK,
        )

        irr = self.get_currency(
            yesterday_response,
            "IRR",
        )

        self.assertEqual(
            irr["captured_amount"],
            "100000.00",
        )
        self.assertEqual(
            irr["net_cash_flow"],
            "100000.00",
        )

    def test_refund_uses_refunded_at_not_paid_at(self):
        self.authenticate(self.superuser)

        yesterday = timezone.now() - timedelta(days=1)

        self.create_payment(
            amount="200000",
            payment_status=Payment.StatusChoices.REFUNDED,
            paid_at=yesterday,
            refunded_at=timezone.now(),
        )

        response = self.client.get(
            self.url,
            {"period": "today"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        irr = self.get_currency(response, "IRR")

        self.assertEqual(
            irr["captured_amount"],
            "0.00",
        )
        self.assertEqual(
            irr["refunded_amount"],
            "200000.00",
        )
        self.assertEqual(
            irr["net_cash_flow"],
            "-200000.00",
        )
        self.assertEqual(
            irr["refunded_payments_count"],
            1,
        )

    def test_refunded_payment_preserves_capture_history(self):
        self.authenticate(self.superuser)

        now = timezone.now()

        self.create_payment(
            amount="300000",
            payment_status=Payment.StatusChoices.REFUNDED,
            paid_at=now - timedelta(days=2),
            refunded_at=now,
        )

        response = self.client.get(
            self.url,
            {"period": "all"},
        )

        irr = self.get_currency(response, "IRR")

        self.assertEqual(
            irr["captured_amount"],
            "300000.00",
        )
        self.assertEqual(
            irr["refunded_amount"],
            "300000.00",
        )
        self.assertEqual(
            irr["net_cash_flow"],
            "0.00",
        )

    def test_different_currencies_are_not_combined(self):
        self.authenticate(self.superuser)

        now = timezone.now()

        self.create_payment(
            amount="900000",
            currency="IRR",
            paid_at=now,
        )
        self.create_payment(
            amount="50",
            currency="USD",
            paid_at=now,
        )

        response = self.client.get(
            self.url,
            {"period": "all"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            len(response.data["currencies"]),
            2,
        )

        irr = self.get_currency(response, "IRR")
        usd = self.get_currency(response, "USD")

        self.assertEqual(
            irr["net_cash_flow"],
            "900000.00",
        )
        self.assertEqual(
            usd["net_cash_flow"],
            "50.00",
        )

    def test_missing_paid_at_is_reported(self):
        self.authenticate(self.superuser)

        self.create_payment(
            amount="100000",
            paid_at=None,
        )

        response = self.client.get(
            self.url,
            {"period": "all"},
        )

        self.assertEqual(
            response.data["currencies"],
            [],
        )

        quality = response.data["data_quality"]

        self.assertTrue(
            quality["has_warnings"],
        )
        self.assertEqual(
            quality["completed_payments_without_paid_at"],
            1,
        )

    def test_missing_refund_timestamp_is_reported(self):
        self.authenticate(self.superuser)

        self.create_payment(
            amount="120000",
            payment_status=Payment.StatusChoices.REFUNDED,
            paid_at=timezone.now(),
            refunded_at=None,
        )

        response = self.client.get(
            self.url,
            {"period": "all"},
        )

        quality = response.data["data_quality"]

        self.assertTrue(
            quality["has_warnings"],
        )
        self.assertEqual(
            quality["refunded_payments_without_refunded_at"],
            1,
        )

    def test_failed_payment_is_not_cash_received(self):
        self.authenticate(self.superuser)

        self.create_payment(
            amount="100000",
            payment_status=Payment.StatusChoices.FAILED,
        )

        response = self.client.get(
            self.url,
            {"period": "all"},
        )

        self.assertEqual(
            response.data["currencies"],
            [],
        )

    def test_incomplete_date_range_is_rejected(self):
        self.authenticate(self.superuser)

        response = self.client.get(
            self.url,
            {"start_date": "2026-10-01"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_reversed_date_range_is_rejected(self):
        self.authenticate(self.superuser)

        response = self.client.get(
            self.url,
            {
                "start_date": "2026-10-18",
                "end_date": "2026-10-01",
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_custom_date_range_handles_dst(self):
        with timezone.override("Europe/Berlin"):
            window = get_financial_window(
                start_date=date(2026, 3, 28),
                end_date=date(2026, 3, 29),
            )

        self.assertEqual(
            window.start_at.date(),
            date(2026, 3, 28),
        )
        self.assertEqual(
            window.end_exclusive_at.date(),
            date(2026, 3, 30),
        )
        self.assertEqual(
            window.start_at.utcoffset(),
            timedelta(hours=1),
        )
        self.assertEqual(
            window.end_exclusive_at.utcoffset(),
            timedelta(hours=2),
        )

    def test_viewer_can_read_financial_metrics(self):
        self.authenticate(self.viewer)

        response = self.client.get(
            self.url,
            {"period": "month"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_regular_staff_is_denied(self):
        self.authenticate(self.regular_staff)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_seller_is_denied_platform_metrics(self):
        self.authenticate(self.seller)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_anonymous_user_is_denied(self):
        response = self.client.get(self.url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )
