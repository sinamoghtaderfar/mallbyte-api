import csv
import io
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.analytics.models import AnalyticsGeneratedReport
from apps.analytics.services import build_csv_export_data, get_scheduled_report_date_range
from apps.analytics.tasks import generate_analytics_report, queue_report, run_due_analytics_report_schedules
from apps.common.exports import safe_spreadsheet_value
from apps.orders.models import Order
from apps.products.views import ProductExportView


class ScheduledPeriodBoundaryTests(SimpleTestCase):
    def test_every_scheduled_period_has_explicit_calendar_boundaries(self):
        at = datetime(2026, 3, 15, 12, tzinfo=UTC)
        expected = {
            "yesterday": ("2026-03-14", "2026-03-14"),
            "last_7_days": ("2026-03-08", "2026-03-14"),
            "last_30_days": ("2026-02-13", "2026-03-14"),
            "this_month": ("2026-03-01", "2026-03-15"),
            "previous_month": ("2026-02-01", "2026-02-28"),
        }
        for period, dates in expected.items():
            start, end = get_scheduled_report_date_range(period, at=at)
            self.assertEqual((start.date().isoformat(), end.date().isoformat()), dates)
            self.assertLess(start, end)
        self.assertEqual(get_scheduled_report_date_range("all", at=at), (None, at))
        with self.assertRaises(ValueError):
            get_scheduled_report_date_range("misspelled", at=at)

    def test_spreadsheet_sanitizer_handles_formula_whitespace_and_preserves_numbers(self):
        for value in ("=1+1", "+cmd", "-cmd", "@SUM(A1)", "  =1+1", "\t=1+1", "\n=1+1"):
            self.assertTrue(safe_spreadsheet_value(value).startswith("'"))
        self.assertEqual(safe_spreadsheet_value(123), 123)
        self.assertEqual(safe_spreadsheet_value("safe"), "safe")


class ReportExecutionHardeningTests(APITestCase):
    def test_scheduled_yesterday_export_excludes_old_and_today_orders(self):
        from django.contrib.auth import get_user_model
        buyer = get_user_model().objects.create_user(email="scheduled-window@example.com")
        at = timezone.now().replace(hour=12)
        orders = [Order.objects.create(user=buyer, subtotal=100) for _ in range(3)]
        for order, days in zip(orders, (0, 1, 2), strict=True):
            Order.objects.filter(pk=order.pk).update(created_at=at - timedelta(days=days))
        result = build_csv_export_data(report="orders", period="yesterday", scheduled=True, at=at)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0][0], orders[1].order_number)

    def test_generated_csv_is_sanitized_and_success_is_idempotent(self):
        report = AnalyticsGeneratedReport.objects.create(report_type="orders", period="yesterday")
        payload = {"headers": ["title"], "rows": [["  =1+1"]], "filename": "safe.csv"}
        with patch("apps.analytics.tasks.build_csv_export_data", return_value=payload) as build:
            first = generate_analytics_report(str(report.pk))
            second = generate_analytics_report(str(report.pk))
        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], "success")
        self.assertEqual(build.call_count, 1)
        report.refresh_from_db()
        with report.file.open("rb") as stored:
            rows = list(csv.reader(io.StringIO(stored.read().decode())))
        self.assertEqual(rows[1][0], "'  =1+1")

    def test_superseded_worker_cannot_replace_successful_recovered_report(self):
        report = AnalyticsGeneratedReport.objects.create(report_type="orders", period="all")
        recovered_payload = {"headers": ["title"], "rows": [["recovered"]], "filename": "recovered.csv"}

        def finish_recovery(**kwargs):
            AnalyticsGeneratedReport.objects.filter(pk=report.pk).update(
                started_at=timezone.now() - timedelta(hours=1),
            )
            with patch("apps.analytics.tasks.build_csv_export_data", return_value=recovered_payload):
                generate_analytics_report(str(report.pk))
            return {"headers": ["title"], "rows": [["obsolete"]], "filename": "obsolete.csv"}

        with patch("apps.analytics.tasks.build_csv_export_data", side_effect=finish_recovery):
            generate_analytics_report(str(report.pk))
        report.refresh_from_db()
        self.assertEqual(report.filename, "recovered.csv")
        self.assertEqual(report.status, "success")
        with report.file.open("rb") as stored:
            self.assertIn(b"recovered", stored.read())

    def test_scheduler_dispatches_only_after_commit_and_recovers_abandoned_job(self):
        report = AnalyticsGeneratedReport.objects.create(report_type="orders", period="all")
        AnalyticsGeneratedReport.objects.filter(pk=report.pk).update(updated_at=timezone.now() - timedelta(minutes=10))
        with patch("apps.analytics.tasks.generate_analytics_report.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                result = run_due_analytics_report_schedules()
                delay.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            delay.assert_called_once_with(str(report.pk))
            self.assertEqual(result["queued_reports"], 1)

    def test_broker_failure_preserves_pending_report_for_recovery(self):
        report = AnalyticsGeneratedReport.objects.create(report_type="orders", period="all")
        with patch("apps.analytics.tasks.generate_analytics_report.delay", side_effect=OSError("private broker details")):
            with self.assertLogs("apps.analytics.tasks", level="ERROR") as logs:
                queue_report(report.pk)
        report.refresh_from_db()
        self.assertEqual(report.status, "pending")
        self.assertNotIn("private broker details", str(logs.output))

    def test_transient_report_failure_requests_bounded_retry_and_hides_exception_details(self):
        report = AnalyticsGeneratedReport.objects.create(report_type="orders", period="all")
        with patch("apps.analytics.tasks.build_csv_export_data", side_effect=OSError("PRIVATE FILE PATH")):
            with patch.object(generate_analytics_report, "retry", side_effect=OSError("retry requested")) as retry:
                with self.assertRaises(OSError):
                    generate_analytics_report(str(report.pk))
        retry.assert_called_once()
        report.refresh_from_db()
        self.assertEqual(report.status, "failed")
        self.assertNotIn("PRIVATE FILE PATH", report.error_message)
        self.assertEqual(generate_analytics_report.max_retries, 3)

    def test_product_csv_and_excel_treat_names_as_data(self):
        from types import SimpleNamespace

        from openpyxl import load_workbook
        product = SimpleNamespace(id=1, name="=1+1", price=100, stock=2, status="approved", category=None, brand=None, created_at=timezone.now())
        view = ProductExportView()
        csv_response = view.export_csv([product])
        self.assertEqual(list(csv.reader(io.StringIO(csv_response.content.decode())))[1][1], "'=1+1")
        workbook = load_workbook(io.BytesIO(view.export_excel([product]).content))
        self.assertEqual(workbook.active["B2"].data_type, "s")
        self.assertEqual(workbook.active["B2"].value, "'=1+1")
        self.assertEqual(workbook.active["C2"].data_type, "n")
