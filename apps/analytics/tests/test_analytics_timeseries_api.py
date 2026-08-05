from datetime import timedelta
from decimal import Decimal
from typing import cast

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.orders.models import Order
from apps.payments.models import Payment


class AnalyticsTimeSeriesAPITests(APITestCase):
    def create_test_user(
        self,
        *,
        phone,
        email,
        full_name,
        password="testpass123",
        is_staff=False,
        is_superuser=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        user.set_password(password)
        user.save()
        return user

    def create_test_order(
        self,
        *,
        user,
        status_value,
        payment_status,
        subtotal,
    ):
        return Order.objects.create(
            user=user,
            status=status_value,
            payment_status=payment_status,
            subtotal=Decimal(str(subtotal)),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name=user.full_name,
            receiver_phone=user.phone,
            province="Tehran",
            city="Tehran",
            address="Analytics test address",
            postal_code="1234567890",
        )

    def create_test_payment(
        self,
        *,
        order,
        user,
        status_value,
        amount,
    ):
        return Payment.objects.create(
            order=order,
            user=user,
            provider=Payment.ProviderChoices.MOCK,
            status=status_value,
            amount=Decimal(str(amount)),
            currency="IRR",
            created_by=self.admin_user,
        )

    def setUp(self):
        self.admin_user = self.create_test_user(
            phone="+989992000001",
            email="timeseries_admin@example.com",
            full_name="Timeseries Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989992000002",
            email="timeseries_customer@example.com",
            full_name="Timeseries Customer",
        )

        self.old_customer = self.create_test_user(
            phone="+989992000003",
            email="timeseries_old_customer@example.com",
            full_name="Timeseries Old Customer",
        )

        now = timezone.now()
        self.today = now.date()
        self.yesterday = self.today - timedelta(days=1)
        self.old_day = self.today - timedelta(days=90)

        today_datetime = now
        yesterday_datetime = now - timedelta(days=1)
        old_datetime = now - timedelta(days=90)

        self.today_paid_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal="200000",
        )

        self.today_pending_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal="50000",
        )

        self.yesterday_paid_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal="100000",
        )

        self.old_paid_order = self.create_test_order(
            user=self.old_customer,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal="300000",
        )

        Order.objects.filter(pk=self.today_paid_order.pk).update(
            created_at=today_datetime
        )
        Order.objects.filter(pk=self.today_pending_order.pk).update(
            created_at=today_datetime
        )
        Order.objects.filter(pk=self.yesterday_paid_order.pk).update(
            created_at=yesterday_datetime
        )
        Order.objects.filter(pk=self.old_paid_order.pk).update(
            created_at=old_datetime
        )

        self.today_success_payment = self.create_test_payment(
            order=self.today_paid_order,
            user=self.customer,
            status_value=Payment.StatusChoices.SUCCESS,
            amount="200000",
        )

        self.today_failed_payment = self.create_test_payment(
            order=self.today_pending_order,
            user=self.customer,
            status_value=Payment.StatusChoices.FAILED,
            amount="50000",
        )

        self.yesterday_success_payment = self.create_test_payment(
            order=self.yesterday_paid_order,
            user=self.customer,
            status_value=Payment.StatusChoices.SUCCESS,
            amount="100000",
        )

        self.old_success_payment = self.create_test_payment(
            order=self.old_paid_order,
            user=self.old_customer,
            status_value=Payment.StatusChoices.SUCCESS,
            amount="300000",
        )

        Payment.objects.filter(pk=self.today_success_payment.pk).update(
            created_at=today_datetime
        )
        Payment.objects.filter(pk=self.today_failed_payment.pk).update(
            created_at=today_datetime
        )
        Payment.objects.filter(pk=self.yesterday_success_payment.pk).update(
            created_at=yesterday_datetime
        )
        Payment.objects.filter(pk=self.old_success_payment.pk).update(
            created_at=old_datetime
        )

        User.objects.filter(pk=self.admin_user.pk).update(
            date_joined=today_datetime
        )
        User.objects.filter(pk=self.customer.pk).update(
            date_joined=today_datetime
        )
        User.objects.filter(pk=self.old_customer.pk).update(
            date_joined=old_datetime
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def get_point(self, data, date_value):
        date_string = date_value.isoformat()

        return next(
            point for point in data["points"] if point["date"] == date_string
        )

    def test_anonymous_user_cannot_access_timeseries(self):
        url = reverse("analytics-timeseries")

        response = self.client.get(url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_customer_cannot_access_timeseries(self):
        self.authenticate_customer()

        url = reverse("analytics-timeseries")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_access_timeseries(self):
        self.authenticate_admin()

        url = reverse("analytics-timeseries")

        response = self.client.get(
            url,
            data={
                "period": "month",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertIn("filters", data)
        self.assertIn("totals", data)
        self.assertIn("points", data)

        self.assertEqual(data["filters"]["period"], "month")
        self.assertGreater(len(data["points"]), 0)

    def test_timeseries_totals_for_month_period(self):
        self.authenticate_admin()

        url = reverse("analytics-timeseries")

        response = self.client.get(
            url,
            data={
                "period": "month",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["totals"]["revenue"], "300000.00")
        self.assertEqual(data["totals"]["orders_count"], 3)
        self.assertEqual(data["totals"]["paid_orders_count"], 2)
        self.assertEqual(data["totals"]["successful_payments_count"], 2)
        self.assertEqual(data["totals"]["new_users_count"], 2)

    def test_timeseries_daily_points_are_correct(self):
        self.authenticate_admin()

        url = reverse("analytics-timeseries")

        response = self.client.get(
            url,
            data={
                "period": "month",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        today_point = self.get_point(data, self.today)
        yesterday_point = self.get_point(data, self.yesterday)

        self.assertEqual(today_point["revenue"], "200000.00")
        self.assertEqual(today_point["orders_count"], 2)
        self.assertEqual(today_point["paid_orders_count"], 1)
        self.assertEqual(today_point["successful_payments_count"], 1)
        self.assertEqual(today_point["new_users_count"], 2)

        self.assertEqual(yesterday_point["revenue"], "100000.00")
        self.assertEqual(yesterday_point["orders_count"], 1)
        self.assertEqual(yesterday_point["paid_orders_count"], 1)
        self.assertEqual(yesterday_point["successful_payments_count"], 1)
        self.assertEqual(yesterday_point["new_users_count"], 0)

    def test_timeseries_excludes_old_data_from_month_period(self):
        self.authenticate_admin()

        url = reverse("analytics-timeseries")

        response = self.client.get(
            url,
            data={
                "period": "month",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        dates = {point["date"] for point in data["points"]}

        self.assertNotIn(self.old_day.isoformat(), dates)
        self.assertEqual(data["totals"]["revenue"], "300000.00")

    def test_timeseries_allows_custom_date_range(self):
        self.authenticate_admin()

        url = reverse("analytics-timeseries")

        response = self.client.get(
            url,
            data={
                "start_date": self.old_day.isoformat(),
                "end_date": self.today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["totals"]["revenue"], "600000.00")
        self.assertEqual(data["totals"]["orders_count"], 4)
        self.assertEqual(data["totals"]["paid_orders_count"], 3)
        self.assertEqual(data["totals"]["successful_payments_count"], 3)
        self.assertEqual(data["totals"]["new_users_count"], 3)

    def test_timeseries_invalid_date_range_returns_error(self):
        self.authenticate_admin()

        url = reverse("analytics-timeseries")

        response = self.client.get(
            url,
            data={
                "start_date": self.today.isoformat(),
                "end_date": self.yesterday.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_timeseries_requires_both_start_and_end_date(self):
        self.authenticate_admin()

        url = reverse("analytics-timeseries")

        response = self.client.get(
            url,
            data={
                "start_date": self.today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)