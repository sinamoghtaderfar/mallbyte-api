import shutil
import tempfile
from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.analytics.models import (
    AnalyticsGeneratedReport,
    AnalyticsReportPeriod,
    AnalyticsReportSchedule,
    AnalyticsReportType,
)
from apps.analytics.tasks import (
    generate_analytics_report,
    run_due_analytics_report_schedules,
)
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Category, Product

TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ScheduledAnalyticsReportsAPITestCase(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()

        self.admin = self.create_user(
            phone="+989900001001",
            email="admin@example.com",
            full_name="Admin User",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_user(
            phone="+989900001002",
            email="customer@example.com",
            full_name="Customer User",
        )

        self.seller = self.create_user(
            phone="+989900001003",
            email="seller@example.com",
            full_name="Seller User",
            is_seller=True,
        )

        self.category = Category.objects.create(
            name="Analytics Test Category",
            slug="analytics-test-category",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Analytics Test Product",
            slug="analytics-test-product",
            sku="ANALYTICS-TEST-001",
            description="Product for scheduled analytics report tests.",
            price=Decimal("1000000"),
            compare_price=Decimal("1200000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            is_featured=True,
        )

        self.order = Order.objects.create(
            order_number="ANALYTICS-ORDER-001",
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("2000000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name=self.customer.full_name,
            receiver_phone=self.customer.phone,
            province="Tehran",
            city="Tehran",
            address="Analytics test address",
            postal_code="1234567890",
            paid_at=timezone.now(),
        )

        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.name,
            product_sku=self.product.sku,
            quantity=2,
            unit_price=Decimal("1000000"),
            total_price=Decimal("2000000"),
        )

        self.payment = Payment.objects.create(
            payment_number="ANALYTICS-PAYMENT-001",
            order=self.order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status=Payment.StatusChoices.SUCCESS,
            amount=Decimal("2000000"),
            currency="IRR",
            paid_at=timezone.now(),
            created_by=self.admin,
        )

    def create_user(
        self,
        *,
        phone,
        email,
        full_name,
        is_staff=False,
        is_superuser=False,
        is_seller=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
            is_seller=is_seller,
        )
        user.set_password("TestPass123!")
        user.save()
        return user

    def authenticate_admin(self):
        self.client.force_authenticate(user=self.admin)

    def authenticate_customer(self):
        self.client.force_authenticate(user=self.customer)

    def create_schedule(self, **overrides):
        data = {
            "name": "Daily Scheduled Analytics Report",
            "report_types": [
                AnalyticsReportType.SALES,
                AnalyticsReportType.ORDERS,
                AnalyticsReportType.PAYMENTS,
            ],
            "period": AnalyticsReportPeriod.ALL,
            "frequency": AnalyticsReportSchedule.FrequencyChoices.DAILY,
            "time_of_day": time(2, 0),
            "is_active": True,
            "created_by": self.admin,
        }
        data.update(overrides)

        return AnalyticsReportSchedule.objects.create(**data)

    def test_anonymous_user_cannot_access_report_schedules(self):
        url = reverse("analytics-report-schedule-list")

        response = self.client.get(url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_customer_cannot_access_report_schedules(self):
        self.authenticate_customer()

        url = reverse("analytics-report-schedule-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_daily_report_schedule(self):
        self.authenticate_admin()

        url = reverse("analytics-report-schedule-list")

        response = self.client.post(
            url,
            {
                "name": "Daily Business Report",
                "report_types": [
                    AnalyticsReportType.SALES,
                    AnalyticsReportType.ORDERS,
                    AnalyticsReportType.PAYMENTS,
                ],
                "period": AnalyticsReportPeriod.YESTERDAY,
                "frequency": AnalyticsReportSchedule.FrequencyChoices.DAILY,
                "time_of_day": "02:00:00",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(AnalyticsReportSchedule.objects.count(), 1)

        schedule = AnalyticsReportSchedule.objects.first()

        self.assertEqual(schedule.name, "Daily Business Report")
        self.assertEqual(schedule.created_by, self.admin)
        self.assertIsNotNone(schedule.next_run_at)

    def test_weekly_schedule_requires_day_of_week(self):
        self.authenticate_admin()

        url = reverse("analytics-report-schedule-list")

        response = self.client.post(
            url,
            {
                "name": "Weekly Business Report",
                "report_types": [
                    AnalyticsReportType.SALES,
                    AnalyticsReportType.ORDERS,
                ],
                "period": AnalyticsReportPeriod.LAST_7_DAYS,
                "frequency": AnalyticsReportSchedule.FrequencyChoices.WEEKLY,
                "time_of_day": "09:00:00",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("day_of_week", response.data)

    def test_admin_can_create_weekly_report_schedule(self):
        self.authenticate_admin()

        url = reverse("analytics-report-schedule-list")

        response = self.client.post(
            url,
            {
                "name": "Weekly Business Report",
                "report_types": [
                    AnalyticsReportType.SALES,
                    AnalyticsReportType.ORDERS,
                ],
                "period": AnalyticsReportPeriod.LAST_7_DAYS,
                "frequency": AnalyticsReportSchedule.FrequencyChoices.WEEKLY,
                "time_of_day": "09:00:00",
                "day_of_week": 0,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        schedule = AnalyticsReportSchedule.objects.get()

        self.assertEqual(schedule.day_of_week, 0)
        self.assertIsNotNone(schedule.next_run_at)

    def test_monthly_schedule_requires_day_of_month(self):
        self.authenticate_admin()

        url = reverse("analytics-report-schedule-list")

        response = self.client.post(
            url,
            {
                "name": "Monthly Business Report",
                "report_types": [
                    AnalyticsReportType.SALES,
                    AnalyticsReportType.ORDERS,
                ],
                "period": AnalyticsReportPeriod.PREVIOUS_MONTH,
                "frequency": AnalyticsReportSchedule.FrequencyChoices.MONTHLY,
                "time_of_day": "08:00:00",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("day_of_month", response.data)

    def test_admin_can_create_monthly_report_schedule(self):
        self.authenticate_admin()

        url = reverse("analytics-report-schedule-list")

        response = self.client.post(
            url,
            {
                "name": "Monthly Business Report",
                "report_types": [
                    AnalyticsReportType.SALES,
                    AnalyticsReportType.ORDERS,
                ],
                "period": AnalyticsReportPeriod.PREVIOUS_MONTH,
                "frequency": AnalyticsReportSchedule.FrequencyChoices.MONTHLY,
                "time_of_day": "08:00:00",
                "day_of_month": 1,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        schedule = AnalyticsReportSchedule.objects.get()

        self.assertEqual(schedule.day_of_month, 1)
        self.assertIsNotNone(schedule.next_run_at)

    def test_every_n_days_schedule_requires_valid_every_n_days(self):
        self.authenticate_admin()

        url = reverse("analytics-report-schedule-list")

        response = self.client.post(
            url,
            {
                "name": "Invalid Every N Days Report",
                "report_types": [
                    AnalyticsReportType.SALES,
                ],
                "period": AnalyticsReportPeriod.LAST_7_DAYS,
                "frequency": AnalyticsReportSchedule.FrequencyChoices.EVERY_N_DAYS,
                "time_of_day": "10:00:00",
                "every_n_days": 0,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("every_n_days", response.data)

    def test_admin_can_create_every_three_days_report_schedule(self):
        self.authenticate_admin()

        url = reverse("analytics-report-schedule-list")

        response = self.client.post(
            url,
            {
                "name": "Every Three Days Business Report",
                "report_types": [
                    AnalyticsReportType.SALES,
                    AnalyticsReportType.SUPPORT,
                ],
                "period": AnalyticsReportPeriod.LAST_7_DAYS,
                "frequency": AnalyticsReportSchedule.FrequencyChoices.EVERY_N_DAYS,
                "time_of_day": "10:00:00",
                "every_n_days": 3,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        schedule = AnalyticsReportSchedule.objects.get()

        self.assertEqual(schedule.every_n_days, 3)
        self.assertIsNotNone(schedule.next_run_at)

    def test_schedule_rejects_empty_report_types(self):
        self.authenticate_admin()

        url = reverse("analytics-report-schedule-list")

        response = self.client.post(
            url,
            {
                "name": "Invalid Empty Report Types",
                "report_types": [],
                "period": AnalyticsReportPeriod.YESTERDAY,
                "frequency": AnalyticsReportSchedule.FrequencyChoices.DAILY,
                "time_of_day": "02:00:00",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("report_types", response.data)

    def test_schedule_rejects_invalid_report_type(self):
        self.authenticate_admin()

        url = reverse("analytics-report-schedule-list")

        response = self.client.post(
            url,
            {
                "name": "Invalid Report Type",
                "report_types": [
                    "wrong_report",
                ],
                "period": AnalyticsReportPeriod.YESTERDAY,
                "frequency": AnalyticsReportSchedule.FrequencyChoices.DAILY,
                "time_of_day": "02:00:00",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("report_types", response.data)

    def test_admin_can_update_report_schedule_and_recalculate_next_run(self):
        self.authenticate_admin()

        schedule = self.create_schedule()
        old_next_run_at = schedule.next_run_at

        url = reverse(
            "analytics-report-schedule-detail",
            kwargs={"pk": schedule.pk},
        )

        response = self.client.patch(
            url,
            {
                "frequency": AnalyticsReportSchedule.FrequencyChoices.WEEKLY,
                "day_of_week": 0,
                "time_of_day": "09:00:00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        schedule.refresh_from_db()

        self.assertEqual(
            schedule.frequency,
            AnalyticsReportSchedule.FrequencyChoices.WEEKLY,
        )
        self.assertEqual(schedule.day_of_week, 0)
        self.assertIsNotNone(schedule.next_run_at)
        self.assertNotEqual(schedule.next_run_at, old_next_run_at)

    def test_run_now_queues_reports_for_schedule(self):
        self.authenticate_admin()

        schedule = self.create_schedule(
            report_types=[
                AnalyticsReportType.SALES,
                AnalyticsReportType.ORDERS,
            ],
        )

        url = reverse(
            "analytics-report-schedule-run-now",
            kwargs={"pk": schedule.pk},
        )

        with patch("apps.analytics.views.generate_analytics_report.delay") as mocked_delay:
            response = self.client.post(url, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(AnalyticsGeneratedReport.objects.count(), 2)
        self.assertEqual(mocked_delay.call_count, 2)
        self.assertEqual(len(response.data["queued_reports"]), 2)

    def test_generate_report_now_endpoint_queues_reports_without_schedule(self):
        self.authenticate_admin()

        url = reverse("analytics-generate-report-now-list")

        with patch("apps.analytics.views.generate_analytics_report.delay") as mocked_delay:
            response = self.client.post(
                url,
                {
                    "report_types": [
                        AnalyticsReportType.SALES,
                        AnalyticsReportType.PAYMENTS,
                    ],
                    "period": AnalyticsReportPeriod.ALL,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(AnalyticsGeneratedReport.objects.count(), 2)
        self.assertEqual(mocked_delay.call_count, 2)

        reports = AnalyticsGeneratedReport.objects.order_by("created_at")

        self.assertEqual(reports[0].schedule, None)
        self.assertEqual(reports[0].generated_by, self.admin)

    def test_customer_cannot_generate_report_now(self):
        self.authenticate_customer()

        url = reverse("analytics-generate-report-now-list")

        response = self.client.post(
            url,
            {
                "report_types": [
                    AnalyticsReportType.SALES,
                ],
                "period": AnalyticsReportPeriod.ALL,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_generated_reports_list_is_admin_only(self):
        self.authenticate_customer()

        url = reverse("analytics-generated-report-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_filter_generated_reports(self):
        self.authenticate_admin()

        AnalyticsGeneratedReport.objects.create(
            report_type=AnalyticsReportType.SALES,
            period=AnalyticsReportPeriod.ALL,
            status=AnalyticsGeneratedReport.StatusChoices.SUCCESS,
            generated_by=self.admin,
        )

        AnalyticsGeneratedReport.objects.create(
            report_type=AnalyticsReportType.ORDERS,
            period=AnalyticsReportPeriod.ALL,
            status=AnalyticsGeneratedReport.StatusChoices.FAILED,
            generated_by=self.admin,
        )

        url = reverse("analytics-generated-report-list")

        response = self.client.get(
            url,
            {
                "status": AnalyticsGeneratedReport.StatusChoices.SUCCESS,
                "report_type": AnalyticsReportType.SALES,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data.get("results", response.data)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["report_type"], AnalyticsReportType.SALES)
        self.assertEqual(
            results[0]["status"],
            AnalyticsGeneratedReport.StatusChoices.SUCCESS,
        )

    def test_run_due_schedules_queues_reports_and_updates_schedule(self):
        schedule = self.create_schedule(
            name="Due Schedule",
            report_types=[
                AnalyticsReportType.SALES,
                AnalyticsReportType.ORDERS,
            ],
            next_run_at=timezone.now() - timedelta(minutes=1),
        )

        with patch("apps.analytics.tasks.generate_analytics_report.delay") as mocked_delay:
            result = run_due_analytics_report_schedules()

        self.assertEqual(result["processed_schedules"], 1)
        self.assertEqual(result["queued_reports"], 2)
        self.assertEqual(mocked_delay.call_count, 2)

        schedule.refresh_from_db()

        self.assertIsNotNone(schedule.last_run_at)
        self.assertGreater(schedule.next_run_at, timezone.now())
        self.assertEqual(schedule.generated_reports.count(), 2)

    def test_run_due_schedules_ignores_inactive_schedules(self):
        self.create_schedule(
            name="Inactive Due Schedule",
            is_active=False,
            next_run_at=timezone.now() - timedelta(minutes=1),
        )

        with patch("apps.analytics.tasks.generate_analytics_report.delay") as mocked_delay:
            result = run_due_analytics_report_schedules()

        self.assertEqual(result["processed_schedules"], 0)
        self.assertEqual(result["queued_reports"], 0)
        self.assertEqual(mocked_delay.call_count, 0)
        self.assertEqual(AnalyticsGeneratedReport.objects.count(), 0)

    def test_generate_analytics_report_task_creates_csv_file(self):
        report = AnalyticsGeneratedReport.objects.create(
            report_type=AnalyticsReportType.SALES,
            period=AnalyticsReportPeriod.ALL,
            generated_by=self.admin,
        )

        result = generate_analytics_report(str(report.id))

        report.refresh_from_db()

        self.assertEqual(
            report.status,
            AnalyticsGeneratedReport.StatusChoices.SUCCESS,
        )
        self.assertEqual(result["status"], AnalyticsGeneratedReport.StatusChoices.SUCCESS)
        self.assertEqual(report.filename, "analytics_sales_export.csv")
        self.assertTrue(report.file)
        self.assertGreaterEqual(report.rows_count, 1)
        self.assertIsNotNone(report.started_at)
        self.assertIsNotNone(report.completed_at)

        with report.file.open("rb") as report_file:
            content = report_file.read().decode("utf-8")

        self.assertTrue(content.strip())
        self.assertIn(",", content)

    def test_generate_analytics_report_task_marks_report_failed_on_error(self):
        report = AnalyticsGeneratedReport.objects.create(
            report_type=AnalyticsReportType.SALES,
            period=AnalyticsReportPeriod.ALL,
            generated_by=self.admin,
        )

        with patch(
            "apps.analytics.tasks.build_csv_export_data",
            side_effect=RuntimeError("Export failed"),
        ):
            result = generate_analytics_report(str(report.id))

        report.refresh_from_db()

        self.assertEqual(
            report.status,
            AnalyticsGeneratedReport.StatusChoices.FAILED,
        )
        self.assertEqual(result["status"], AnalyticsGeneratedReport.StatusChoices.FAILED)
        self.assertIn("Export failed", report.error_message)
        self.assertIsNotNone(report.completed_at)

    def test_admin_can_download_successful_generated_report(self):
        self.authenticate_admin()

        report = AnalyticsGeneratedReport.objects.create(
            report_type=AnalyticsReportType.SALES,
            period=AnalyticsReportPeriod.ALL,
            status=AnalyticsGeneratedReport.StatusChoices.SUCCESS,
            filename="test-report.csv",
            generated_by=self.admin,
        )
        report.file.save(
            "test-report.csv",
            ContentFile(b"column_one,column_two\n1,2\n"),
            save=True,
        )

        url = reverse(
            "analytics-generated-report-download",
            kwargs={"pk": report.pk},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("test-report.csv", response["Content-Disposition"])

    def test_download_failed_report_returns_not_found(self):
        self.authenticate_admin()

        report = AnalyticsGeneratedReport.objects.create(
            report_type=AnalyticsReportType.SALES,
            period=AnalyticsReportPeriod.ALL,
            status=AnalyticsGeneratedReport.StatusChoices.FAILED,
            error_message="failed",
            generated_by=self.admin,
        )

        url = reverse(
            "analytics-generated-report-download",
            kwargs={"pk": report.pk},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)