from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.analytics.models import AnalyticsGeneratedReport
from apps.rbac.models import Role
from apps.rbac.utils import assign_role, remove_role


class AnalyticsRBACTests(APITestCase):
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
        self.viewer = self.create_user(
            phone="+989970000001",
            email="analytics-viewer@example.com",
        )
        self.manager = self.create_user(
            phone="+989970000002",
            email="analytics-manager@example.com",
        )
        self.regular_staff = self.create_user(
            phone="+989970000003",
            email="regular-staff@example.com",
            is_staff=True,
        )
        self.customer = self.create_user(
            phone="+989970000004",
            email="customer@example.com",
        )
        self.seller = self.create_user(
            phone="+989970000005",
            email="seller@example.com",
            is_seller=True,
        )
        self.superuser = self.create_user(
            phone="+989970000006",
            email="superuser@example.com",
            is_superuser=True,
        )

        self.viewer_role = Role.objects.get(
            name="analytics_viewer",
        )
        self.manager_role = Role.objects.get(
            name="analytics_manager",
        )

        assign_role(
            self.viewer,
            self.viewer_role,
        )
        assign_role(
            self.manager,
            self.manager_role,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_anonymous_cannot_access_dashboard(self):
        response = self.client.get(
            reverse("analytics-dashboard"),
        )
        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_viewer_can_access_dashboard(self):
        self.authenticate(self.viewer)

        with patch(
            "apps.analytics.views.get_dashboard_analytics",
            return_value={"ok": True},
        ):
            response = self.client.get(
                reverse("analytics-dashboard"),
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_viewer_can_access_read_only_metrics(self):
        self.authenticate(self.viewer)

        cases = [
            (
                "analytics-timeseries",
                "get_analytics_timeseries",
            ),
            (
                "analytics-breakdown",
                "get_analytics_breakdown",
            ),
            (
                "analytics-alerts",
                "get_analytics_alerts",
            ),
        ]

        for url_name, function_name in cases:
            with self.subTest(endpoint=url_name):
                with patch(
                    f"apps.analytics.views.{function_name}",
                    return_value={"ok": True},
                ):
                    response = self.client.get(
                        reverse(url_name),
                    )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_200_OK,
                )

    def test_viewer_cannot_export(self):
        self.authenticate(self.viewer)

        response = self.client.get(
            reverse("analytics-export"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_viewer_cannot_manage_schedules(self):
        self.authenticate(self.viewer)

        response = self.client.get(
            reverse("analytics-report-schedule-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_viewer_cannot_generate_reports(self):
        self.authenticate(self.viewer)

        response = self.client.post(
            reverse("analytics-generate-report-now-list"),
            data={
                "report_types": ["sales"],
                "period": "yesterday",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_viewer_cannot_access_generated_report_urls(self):
        report = AnalyticsGeneratedReport.objects.create(
            report_type="sales",
            period="yesterday",
            status="success",
            file="analytics/reports/private-report.csv",
        )

        self.authenticate(self.viewer)

        urls = [
            reverse("analytics-generated-report-list"),
            reverse(
                "analytics-generated-report-detail",
                args=[report.pk],
            ),
            reverse(
                "analytics-generated-report-download",
                args=[report.pk],
            ),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(
                    response.status_code,
                    status.HTTP_403_FORBIDDEN,
                )

    def test_manager_can_access_dashboard(self):
        self.authenticate(self.manager)

        with patch(
            "apps.analytics.views.get_dashboard_analytics",
            return_value={"ok": True},
        ):
            response = self.client.get(
                reverse("analytics-dashboard"),
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_manager_can_export_csv(self):
        self.authenticate(self.manager)

        with patch(
            "apps.analytics.views.build_csv_export_data",
            return_value={
                "filename": "test.csv",
                "headers": ["id"],
                "rows": [["1"]],
            },
        ):
            response = self.client.get(
                reverse("analytics-export"),
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertIn(
            "text/csv",
            response["Content-Type"],
        )

    def test_manager_can_view_report_management(self):
        self.authenticate(self.manager)

        urls = [
            reverse("analytics-report-schedule-list"),
            reverse("analytics-generated-report-list"),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_200_OK,
                )

    def test_regular_staff_has_no_analytics_privileges(self):
        self.authenticate(self.regular_staff)

        urls = [
            reverse("analytics-dashboard"),
            reverse("analytics-export"),
            reverse("analytics-report-schedule-list"),
            reverse("analytics-generated-report-list"),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(
                    response.status_code,
                    status.HTTP_403_FORBIDDEN,
                )

    def test_seller_cannot_access_platform_analytics(self):
        self.authenticate(self.seller)

        response = self.client.get(
            reverse("analytics-dashboard"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_customer_cannot_access_platform_analytics(self):
        self.authenticate(self.customer)

        response = self.client.get(
            reverse("analytics-dashboard"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_superuser_can_access_platform_analytics(self):
        self.authenticate(self.superuser)

        with patch(
            "apps.analytics.views.get_dashboard_analytics",
            return_value={"ok": True},
        ):
            response = self.client.get(
                reverse("analytics-dashboard"),
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_expired_role_cannot_access_dashboard(self):
        assign_role(
            self.viewer,
            self.viewer_role,
            expires_at=timezone.now() - timedelta(days=1),
        )

        self.authenticate(self.viewer)

        response = self.client.get(
            reverse("analytics-dashboard"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_revoked_role_cannot_access_dashboard(self):
        remove_role(
            self.viewer,
            self.viewer_role,
        )

        self.authenticate(self.viewer)

        response = self.client.get(
            reverse("analytics-dashboard"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )
