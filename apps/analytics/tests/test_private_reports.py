import io
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.analytics.models import AnalyticsGeneratedReport
from apps.analytics.serializers import AnalyticsGeneratedReportSerializer


class PrivateFinancialReportTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_superuser(email="private-report-admin@example.com", password="TestPassword123!")
        self.customer = user_model.objects.create_user(email="private-report-buyer@example.com", password="TestPassword123!")

    def test_report_has_no_public_url_and_download_requires_report_permission(self):
        with tempfile.TemporaryDirectory() as root, override_settings(SUPPORT_PRIVATE_MEDIA_ROOT=root):
            report = AnalyticsGeneratedReport.objects.create(report_type="orders", period="all", status="success")
            report.file.save("report.csv", ContentFile(b"customer_email,total\nprivate@example.com,100\n"))
            with self.assertRaises(ValueError):
                _ = report.file.url
            self.assertTrue(Path(report.file.path).is_relative_to(Path(root)))
            url = reverse("analytics-generated-report-download", args=[report.pk])
            serialized = AnalyticsGeneratedReportSerializer(report).data
            self.assertEqual(serialized["file"], url)
            self.assertEqual(serialized["file_url"], url)
            for user, expected in ((None, 401), (self.customer, 403), (self.admin, 200)):
                self.client.force_authenticate(user=user)
                response = self.client.get(url)
                self.assertEqual(response.status_code, expected)
                if expected == 200:
                    self.assertEqual(response["Cache-Control"], "private, no-store")
                    self.assertEqual(response["X-Content-Type-Options"], "nosniff")
                    self.assertIn(b"private@example.com", b"".join(response.streaming_content))

    def test_legacy_migration_is_dry_by_default_and_verifies_content_before_purge(self):
        with tempfile.TemporaryDirectory() as public, tempfile.TemporaryDirectory() as private:
            with override_settings(MEDIA_ROOT=public, SUPPORT_PRIVATE_MEDIA_ROOT=private):
                name = "analytics/reports/legacy.csv"
                report = AnalyticsGeneratedReport.objects.create(report_type="orders", period="all", file=name)
                source, target = Path(public) / name, Path(private) / name
                source.parent.mkdir(parents=True)
                source.write_bytes(b"private legacy report")
                call_command("migrate_private_media", stdout=io.StringIO())
                self.assertFalse(target.exists())
                call_command("migrate_private_media", apply=True, stdout=io.StringIO())
                self.assertEqual(target.read_bytes(), source.read_bytes())
                target.write_bytes(b"different same length")
                with self.assertRaises(CommandError):
                    call_command("migrate_private_media", apply=True, purge_public=True, stdout=io.StringIO())
                self.assertTrue(source.exists())
                target.write_bytes(source.read_bytes())
                call_command("migrate_private_media", apply=True, purge_public=True, stdout=io.StringIO())
                self.assertFalse(source.exists())
                report.refresh_from_db()
                self.assertEqual(report.file.name, name)
