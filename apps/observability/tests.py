from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.observability.middleware import RequestLogMiddleware
from apps.observability.models import (
    AuditLog,
    CeleryTaskLog,
    ErrorLog,
    HealthStatusChoices,
    ObservabilityAlert,
    RequestLog,
    SeverityChoices,
    SystemHealthSnapshot,
)
from apps.observability.services import (
    build_error_fingerprint,
    cleanup_old_observability_logs,
    collect_system_health_snapshot,
    create_audit_log,
    create_error_log_from_exception,
    create_or_update_alert,
    create_request_log,
    evaluate_error_spike_alert,
    evaluate_slow_request_alert,
    get_client_ip,
    should_skip_observability_path,
)
from apps.observability.signals import log_task_finished, log_task_started


class ObservabilityTestMixin:
    def create_user(
        self,
        *,
        phone,
        email,
        full_name,
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
        user.set_password("TestPass123!")
        user.save()
        return user

    def create_admin_user(self):
        return self.create_user(
            phone="+989900100001",
            email="observability-admin@example.com",
            full_name="Observability Admin",
            is_staff=True,
            is_superuser=True,
        )

    def create_customer_user(self):
        return self.create_user(
            phone="+989900100002",
            email="observability-customer@example.com",
            full_name="Observability Customer",
        )

    def create_snapshot(self, **overrides):
        data = {
            "status": HealthStatusChoices.HEALTHY,
            "hostname": "test-host",
            "os_name": "Linux-test",
            "kernel_version": "test-kernel",
            "uptime_seconds": 1000,
            "load_average_1m": Decimal("0.10"),
            "load_average_5m": Decimal("0.20"),
            "load_average_15m": Decimal("0.30"),
            "cpu_percent": Decimal("10.00"),
            "memory_percent": Decimal("40.00"),
            "disk_percent": Decimal("20.00"),
            "process_count": 100,
            "database_status": HealthStatusChoices.HEALTHY,
            "database_latency_ms": 1,
            "redis_status": HealthStatusChoices.HEALTHY,
            "redis_latency_ms": 2,
            "celery_status": HealthStatusChoices.HEALTHY,
            "celery_beat_status": HealthStatusChoices.HEALTHY,
            "metadata": {
                "database_error": "",
                "redis_error": "",
                "celery_error": "",
                "celery_workers": {
                    "celery@test-host": {
                        "ok": "pong",
                    }
                },
                "celery_beat_error": "",
            },
        }
        data.update(overrides)

        return SystemHealthSnapshot.objects.create(**data)


class ObservabilityAPITestCase(ObservabilityTestMixin, APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = self.create_admin_user()
        self.customer = self.create_customer_user()

    def authenticate_admin(self):
        self.client.force_authenticate(user=self.admin)

    def authenticate_customer(self):
        self.client.force_authenticate(user=self.customer)

    def test_anonymous_user_cannot_access_health_endpoint(self):
        url = reverse("observability-health")

        response = self.client.get(url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_customer_cannot_access_health_endpoint(self):
        self.authenticate_customer()

        url = reverse("observability-health")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_access_health_endpoint(self):
        self.authenticate_admin()

        snapshot = self.create_snapshot()

        url = reverse("observability-health")

        with patch(
            "apps.observability.views.collect_system_health_snapshot",
            return_value=snapshot,
        ):
            response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], HealthStatusChoices.HEALTHY)
        self.assertEqual(response.data["database_status"], HealthStatusChoices.HEALTHY)
        self.assertEqual(response.data["redis_status"], HealthStatusChoices.HEALTHY)
        self.assertEqual(response.data["celery_status"], HealthStatusChoices.HEALTHY)
        self.assertEqual(response.data["celery_beat_status"], HealthStatusChoices.HEALTHY)

    def test_admin_can_access_stats_endpoint(self):
        self.authenticate_admin()

        RequestLog.objects.create(
            user=self.admin,
            method="GET",
            path="/api/test/",
            status_code=200,
            duration_ms=120,
            ip_address="127.0.0.1",
        )
        RequestLog.objects.create(
            user=self.admin,
            method="GET",
            path="/api/slow/",
            status_code=200,
            duration_ms=1500,
            ip_address="127.0.0.1",
        )
        ErrorLog.objects.create(
            severity=SeverityChoices.ERROR,
            exception_type="TestError",
            message="Test error",
            method="GET",
            path="/api/error/",
            status_code=500,
        )
        ObservabilityAlert.objects.create(
            alert_type=ObservabilityAlert.AlertTypeChoices.SYSTEM,
            severity=SeverityChoices.WARNING,
            title="Test alert",
            message="Test alert message",
            source="django",
            fingerprint="test:alert",
        )

        url = reverse("observability-stats")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["window"], "last_24_hours")
        self.assertGreaterEqual(response.data["requests_count"], 2)
        self.assertGreaterEqual(response.data["error_logs_count"], 1)
        self.assertGreaterEqual(response.data["open_alerts_count"], 1)
        self.assertGreaterEqual(response.data["slow_requests_count"], 1)
        self.assertIn("status_codes", response.data)
        self.assertIn("top_paths", response.data)
        self.assertIn("open_alerts_by_severity", response.data)

    def test_request_logs_list_and_filters(self):
        self.authenticate_admin()

        RequestLog.objects.create(
            user=self.admin,
            method="GET",
            path="/api/observability/health/",
            status_code=200,
            duration_ms=50,
            ip_address="127.0.0.1",
        )
        RequestLog.objects.create(
            user=self.admin,
            method="POST",
            path="/api/orders/",
            status_code=500,
            duration_ms=1500,
            ip_address="127.0.0.1",
        )

        url = reverse("observability-request-log-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 2)

        response = self.client.get(url, {"method": "POST"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertTrue(
            any(item["method"] == "POST" for item in results)
        )

        response = self.client.get(url, {"slow": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertTrue(
            all(item["duration_ms"] >= 1000 for item in results)
        )

        response = self.client.get(url, {"error": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertTrue(
            all(item["status_code"] >= 500 for item in results)
        )

    def test_error_logs_list_filter_and_resolve(self):
        self.authenticate_admin()

        error_log = ErrorLog.objects.create(
            severity=SeverityChoices.ERROR,
            exception_type="ManualTestError",
            message="Manual test error",
            method="GET",
            path="/api/test-error/",
            status_code=500,
            fingerprint="manual:test-error",
        )

        url = reverse("observability-error-log-list")

        response = self.client.get(
            url,
            {
                "severity": SeverityChoices.ERROR,
                "exception_type": "ManualTestError",
                "is_resolved": "false",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 1)

        resolve_url = reverse(
            "observability-error-log-resolve",
            kwargs={"pk": error_log.pk},
        )

        response = self.client.post(resolve_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        error_log.refresh_from_db()

        self.assertTrue(error_log.is_resolved)
        self.assertEqual(error_log.resolved_by, self.admin)
        self.assertIsNotNone(error_log.resolved_at)

    def test_audit_logs_list_and_filters(self):
        self.authenticate_admin()

        AuditLog.objects.create(
            actor=self.admin,
            action=AuditLog.ActionChoices.EXPORT,
            object_type="AnalyticsGeneratedReport",
            object_id="123",
            description="Admin exported analytics report.",
            ip_address="127.0.0.1",
        )

        url = reverse("observability-audit-log-list")

        response = self.client.get(
            url,
            {
                "action": AuditLog.ActionChoices.EXPORT,
                "object_type": "AnalyticsGeneratedReport",
                "object_id": "123",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 1)

        result = response.data["results"][0]

        self.assertEqual(result["action"], AuditLog.ActionChoices.EXPORT)
        self.assertEqual(result["object_type"], "AnalyticsGeneratedReport")
        self.assertEqual(result["object_id"], "123")

    def test_system_health_snapshots_list_and_filter(self):
        self.authenticate_admin()

        self.create_snapshot(status=HealthStatusChoices.HEALTHY)
        self.create_snapshot(status=HealthStatusChoices.UNHEALTHY)

        url = reverse("observability-system-health-snapshot-list")

        response = self.client.get(
            url,
            {
                "status": HealthStatusChoices.UNHEALTHY,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 1)

        results = response.data.get("results", response.data)

        self.assertTrue(
            all(item["status"] == HealthStatusChoices.UNHEALTHY for item in results)
        )

    def test_alerts_list_filter_acknowledge_and_resolve(self):
        self.authenticate_admin()

        alert = ObservabilityAlert.objects.create(
            alert_type=ObservabilityAlert.AlertTypeChoices.CELERY,
            severity=SeverityChoices.ERROR,
            title="Celery worker health check failed",
            message="No Celery workers responded.",
            source="celery",
            fingerprint="celery:worker:unhealthy",
        )

        url = reverse("observability-alert-list")

        response = self.client.get(
            url,
            {
                "status": ObservabilityAlert.StatusChoices.OPEN,
                "severity": SeverityChoices.ERROR,
                "alert_type": ObservabilityAlert.AlertTypeChoices.CELERY,
                "source": "celery",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 1)

        acknowledge_url = reverse(
            "observability-alert-acknowledge",
            kwargs={"pk": alert.pk},
        )

        response = self.client.post(acknowledge_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        alert.refresh_from_db()

        self.assertEqual(alert.status, ObservabilityAlert.StatusChoices.ACKNOWLEDGED)
        self.assertEqual(alert.acknowledged_by, self.admin)
        self.assertIsNotNone(alert.acknowledged_at)

        resolve_url = reverse(
            "observability-alert-resolve",
            kwargs={"pk": alert.pk},
        )

        response = self.client.post(resolve_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        alert.refresh_from_db()

        self.assertEqual(alert.status, ObservabilityAlert.StatusChoices.RESOLVED)
        self.assertEqual(alert.resolved_by, self.admin)
        self.assertIsNotNone(alert.resolved_at)

    def test_celery_task_logs_list_and_filters(self):
        self.authenticate_admin()

        CeleryTaskLog.objects.create(
            task_id="task-success-1",
            task_name="apps.observability.tasks.collect_observability_health_snapshot",
            status=CeleryTaskLog.StatusChoices.SUCCESS,
            started_at=timezone.now(),
            finished_at=timezone.now(),
            duration_ms=100,
            result_summary="success",
        )

        CeleryTaskLog.objects.create(
            task_id="task-failure-1",
            task_name="apps.analytics.tasks.generate_analytics_report",
            status=CeleryTaskLog.StatusChoices.FAILURE,
            started_at=timezone.now(),
            finished_at=timezone.now(),
            duration_ms=200,
            error_message="failed",
        )

        url = reverse("observability-celery-task-log-list")

        response = self.client.get(
            url,
            {
                "status": CeleryTaskLog.StatusChoices.SUCCESS,
                "task_name": "collect_observability",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 1)

        results = response.data.get("results", response.data)

        self.assertTrue(
            all(item["status"] == CeleryTaskLog.StatusChoices.SUCCESS for item in results)
        )

    def test_customer_cannot_access_request_logs(self):
        self.authenticate_customer()

        url = reverse("observability-request-log-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ObservabilityServicesTestCase(ObservabilityTestMixin, APITestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = self.create_admin_user()

    def test_get_client_ip_uses_forwarded_for(self):
        request = self.factory.get(
            "/api/test/",
            HTTP_X_FORWARDED_FOR="10.0.0.1, 10.0.0.2",
            REMOTE_ADDR="127.0.0.1",
        )

        ip_address = get_client_ip(request)

        self.assertEqual(ip_address, "10.0.0.1")

    @override_settings(
        OBSERVABILITY_EXCLUDED_PATH_PREFIXES=[
            "/static/",
            "/media/",
        ]
    )
    def test_should_skip_observability_path(self):
        self.assertTrue(should_skip_observability_path("/static/app.css"))
        self.assertTrue(should_skip_observability_path("/media/image.png"))
        self.assertFalse(should_skip_observability_path("/api/orders/"))

    def test_build_error_fingerprint_is_stable(self):
        fingerprint_one = build_error_fingerprint(
            exception_type="ValueError",
            path="/api/test/",
            message="Something failed",
        )
        fingerprint_two = build_error_fingerprint(
            exception_type="ValueError",
            path="/api/test/",
            message="Something failed",
        )

        self.assertEqual(fingerprint_one, fingerprint_two)
        self.assertEqual(len(fingerprint_one), 64)

    def test_create_request_log(self):
        request = self.factory.get(
            "/api/test/?page=1",
            HTTP_USER_AGENT="pytest",
            REMOTE_ADDR="127.0.0.1",
        )
        request.user = self.admin

        response = HttpResponse("OK", status=200)

        request_log = create_request_log(
            request=request,
            response=response,
            duration_ms=123,
            request_id="test-request-id",
        )

        self.assertIsNotNone(request_log)
        self.assertEqual(request_log.user, self.admin)
        self.assertEqual(request_log.request_id, "test-request-id")
        self.assertEqual(request_log.method, "GET")
        self.assertEqual(request_log.path, "/api/test/")
        self.assertEqual(request_log.query_string, "page=1")
        self.assertEqual(request_log.status_code, 200)
        self.assertEqual(request_log.duration_ms, 123)
        self.assertEqual(request_log.ip_address, "127.0.0.1")
        self.assertEqual(request_log.user_agent, "pytest")

    @override_settings(
        OBSERVABILITY_EXCLUDED_PATH_PREFIXES=[
            "/static/",
        ]
    )
    def test_create_request_log_returns_none_for_excluded_path(self):
        request = self.factory.get(
            "/static/app.css",
            HTTP_USER_AGENT="pytest",
            REMOTE_ADDR="127.0.0.1",
        )
        request.user = self.admin

        response = HttpResponse("OK", status=200)

        request_log = create_request_log(
            request=request,
            response=response,
            duration_ms=10,
            request_id="static-request",
        )

        self.assertIsNone(request_log)

    def test_create_error_log_from_exception_creates_alert(self):
        request = self.factory.get(
            "/api/test-error/",
            HTTP_USER_AGENT="pytest",
            REMOTE_ADDR="127.0.0.1",
        )
        request.user = self.admin
        request.observability_request_id = "error-request-id"

        try:
            raise ValueError("Manual service error")
        except ValueError as exc:
            error_log = create_error_log_from_exception(
                request=request,
                exception=exc,
            )

        self.assertIsNotNone(error_log)
        self.assertEqual(error_log.user, self.admin)
        self.assertEqual(error_log.exception_type, "ValueError")
        self.assertEqual(error_log.message, "Manual service error")
        self.assertEqual(error_log.path, "/api/test-error/")
        self.assertEqual(error_log.status_code, 500)
        self.assertFalse(error_log.is_resolved)

        alert = ObservabilityAlert.objects.get(
            related_object_type="ErrorLog",
            related_object_id=str(error_log.id),
        )

        self.assertEqual(alert.alert_type, ObservabilityAlert.AlertTypeChoices.ERROR_SPIKE)
        self.assertEqual(alert.severity, SeverityChoices.ERROR)
        self.assertEqual(alert.source, "django")

    def test_create_audit_log(self):
        request = self.factory.post(
            "/api/admin/action/",
            HTTP_USER_AGENT="pytest",
            REMOTE_ADDR="127.0.0.1",
        )

        audit_log = create_audit_log(
            actor=self.admin,
            action=AuditLog.ActionChoices.EXPORT,
            description="Admin exported a report.",
            object_type="AnalyticsGeneratedReport",
            object_id="report-1",
            request=request,
            metadata={
                "report_type": "sales",
            },
        )

        self.assertEqual(audit_log.actor, self.admin)
        self.assertEqual(audit_log.action, AuditLog.ActionChoices.EXPORT)
        self.assertEqual(audit_log.object_type, "AnalyticsGeneratedReport")
        self.assertEqual(audit_log.object_id, "report-1")
        self.assertEqual(audit_log.ip_address, "127.0.0.1")
        self.assertEqual(audit_log.user_agent, "pytest")
        self.assertEqual(audit_log.metadata["report_type"], "sales")

    def test_create_or_update_alert_does_not_create_duplicates(self):
        alert_one = create_or_update_alert(
            alert_type=ObservabilityAlert.AlertTypeChoices.REDIS,
            severity=SeverityChoices.ERROR,
            title="Redis health check failed",
            message="Redis did not respond.",
            source="redis",
            fingerprint="redis:unhealthy",
            metadata={
                "attempt": 1,
            },
        )

        alert_two = create_or_update_alert(
            alert_type=ObservabilityAlert.AlertTypeChoices.REDIS,
            severity=SeverityChoices.CRITICAL,
            title="Redis is still down",
            message="Redis still did not respond.",
            source="redis",
            fingerprint="redis:unhealthy",
            metadata={
                "attempt": 2,
            },
        )

        self.assertEqual(alert_one.id, alert_two.id)
        self.assertEqual(ObservabilityAlert.objects.count(), 1)

        alert_one.refresh_from_db()

        self.assertEqual(alert_one.severity, SeverityChoices.CRITICAL)
        self.assertEqual(alert_one.title, "Redis is still down")
        self.assertEqual(alert_one.metadata["attempt"], 2)

    @override_settings(
        OBSERVABILITY_CPU_WARNING_PERCENT=90,
        OBSERVABILITY_MEMORY_WARNING_PERCENT=90,
        OBSERVABILITY_DISK_WARNING_PERCENT=85,
    )
    @patch("apps.observability.services.check_celery_beat_health")
    @patch("apps.observability.services.check_celery_worker_health")
    @patch("apps.observability.services.check_redis_health")
    @patch("apps.observability.services.check_database_health")
    @patch("apps.observability.services.get_linux_system_metrics")
    def test_collect_system_health_snapshot_creates_healthy_snapshot(
        self,
        mocked_system_metrics,
        mocked_database_health,
        mocked_redis_health,
        mocked_celery_health,
        mocked_celery_beat_health,
    ):
        mocked_system_metrics.return_value = {
            "hostname": "test-host",
            "os_name": "Linux-test",
            "kernel_version": "test-kernel",
            "uptime_seconds": 1000,
            "load_average_1m": Decimal("0.10"),
            "load_average_5m": Decimal("0.20"),
            "load_average_15m": Decimal("0.30"),
            "cpu_percent": Decimal("10.00"),
            "memory_percent": Decimal("40.00"),
            "disk_percent": Decimal("20.00"),
            "process_count": 100,
        }
        mocked_database_health.return_value = {
            "status": HealthStatusChoices.HEALTHY,
            "latency_ms": 1,
            "error": "",
        }
        mocked_redis_health.return_value = {
            "status": HealthStatusChoices.HEALTHY,
            "latency_ms": 2,
            "error": "",
        }
        mocked_celery_health.return_value = {
            "status": HealthStatusChoices.HEALTHY,
            "workers": {
                "celery@test-host": {
                    "ok": "pong",
                }
            },
            "error": "",
        }
        mocked_celery_beat_health.return_value = {
            "status": HealthStatusChoices.HEALTHY,
            "last_run_at": timezone.now(),
            "error": "",
        }

        snapshot = collect_system_health_snapshot()

        self.assertEqual(snapshot.status, HealthStatusChoices.HEALTHY)
        self.assertEqual(snapshot.database_status, HealthStatusChoices.HEALTHY)
        self.assertEqual(snapshot.redis_status, HealthStatusChoices.HEALTHY)
        self.assertEqual(snapshot.celery_status, HealthStatusChoices.HEALTHY)
        self.assertEqual(snapshot.celery_beat_status, HealthStatusChoices.HEALTHY)
        self.assertEqual(SystemHealthSnapshot.objects.count(), 1)
        self.assertEqual(ObservabilityAlert.objects.count(), 0)

    @patch("apps.observability.services.check_celery_beat_health")
    @patch("apps.observability.services.check_celery_worker_health")
    @patch("apps.observability.services.check_redis_health")
    @patch("apps.observability.services.check_database_health")
    @patch("apps.observability.services.get_linux_system_metrics")
    def test_collect_system_health_snapshot_creates_alert_when_celery_unhealthy(
        self,
        mocked_system_metrics,
        mocked_database_health,
        mocked_redis_health,
        mocked_celery_health,
        mocked_celery_beat_health,
    ):
        mocked_system_metrics.return_value = {
            "hostname": "test-host",
            "os_name": "Linux-test",
            "kernel_version": "test-kernel",
            "uptime_seconds": 1000,
            "load_average_1m": Decimal("0.10"),
            "load_average_5m": Decimal("0.20"),
            "load_average_15m": Decimal("0.30"),
            "cpu_percent": Decimal("10.00"),
            "memory_percent": Decimal("40.00"),
            "disk_percent": Decimal("20.00"),
            "process_count": 100,
        }
        mocked_database_health.return_value = {
            "status": HealthStatusChoices.HEALTHY,
            "latency_ms": 1,
            "error": "",
        }
        mocked_redis_health.return_value = {
            "status": HealthStatusChoices.HEALTHY,
            "latency_ms": 2,
            "error": "",
        }
        mocked_celery_health.return_value = {
            "status": HealthStatusChoices.UNHEALTHY,
            "workers": {},
            "error": "No Celery workers responded.",
        }
        mocked_celery_beat_health.return_value = {
            "status": HealthStatusChoices.HEALTHY,
            "last_run_at": timezone.now(),
            "error": "",
        }

        snapshot = collect_system_health_snapshot()

        self.assertEqual(snapshot.status, HealthStatusChoices.UNHEALTHY)
        self.assertEqual(snapshot.celery_status, HealthStatusChoices.UNHEALTHY)

        alert = ObservabilityAlert.objects.get(
            fingerprint="celery:worker:unhealthy",
        )

        self.assertEqual(alert.alert_type, ObservabilityAlert.AlertTypeChoices.CELERY)
        self.assertEqual(alert.severity, SeverityChoices.ERROR)
        self.assertEqual(alert.status, ObservabilityAlert.StatusChoices.OPEN)

    @override_settings(
        OBSERVABILITY_ERROR_SPIKE_WINDOW_MINUTES=10,
        OBSERVABILITY_ERROR_SPIKE_THRESHOLD=2,
    )
    def test_evaluate_error_spike_alert(self):
        ErrorLog.objects.create(
            severity=SeverityChoices.ERROR,
            exception_type="ValueError",
            message="Error one",
            method="GET",
            path="/api/error-one/",
            status_code=500,
        )
        ErrorLog.objects.create(
            severity=SeverityChoices.ERROR,
            exception_type="TypeError",
            message="Error two",
            method="GET",
            path="/api/error-two/",
            status_code=500,
        )

        evaluate_error_spike_alert()

        alert = ObservabilityAlert.objects.get(
            fingerprint="django:error-spike",
        )

        self.assertEqual(alert.severity, SeverityChoices.CRITICAL)
        self.assertEqual(alert.alert_type, ObservabilityAlert.AlertTypeChoices.ERROR_SPIKE)

    @override_settings(
        OBSERVABILITY_SLOW_REQUEST_THRESHOLD_MS=1000,
    )
    def test_evaluate_slow_request_alert(self):
        for index in range(5):
            RequestLog.objects.create(
                user=self.admin,
                method="GET",
                path=f"/api/slow/{index}/",
                status_code=200,
                duration_ms=1200,
                ip_address="127.0.0.1",
            )

        evaluate_slow_request_alert()

        alert = ObservabilityAlert.objects.get(
            fingerprint="django:slow-requests",
        )

        self.assertEqual(alert.severity, SeverityChoices.WARNING)
        self.assertEqual(alert.alert_type, ObservabilityAlert.AlertTypeChoices.SLOW_REQUEST)

    def test_cleanup_old_observability_logs(self):
        old_date = timezone.now() - timedelta(days=40)

        old_request_log = RequestLog.objects.create(
            user=self.admin,
            method="GET",
            path="/api/old-request/",
            status_code=200,
            duration_ms=50,
            ip_address="127.0.0.1",
        )
        RequestLog.objects.filter(id=old_request_log.id).update(created_at=old_date)

        old_resolved_error = ErrorLog.objects.create(
            severity=SeverityChoices.ERROR,
            exception_type="OldResolvedError",
            message="Old resolved error",
            method="GET",
            path="/api/old-error/",
            status_code=500,
            is_resolved=True,
            resolved_at=timezone.now(),
        )
        ErrorLog.objects.filter(id=old_resolved_error.id).update(created_at=old_date)

        old_unresolved_error = ErrorLog.objects.create(
            severity=SeverityChoices.ERROR,
            exception_type="OldUnresolvedError",
            message="Old unresolved error",
            method="GET",
            path="/api/old-unresolved-error/",
            status_code=500,
            is_resolved=False,
        )
        ErrorLog.objects.filter(id=old_unresolved_error.id).update(created_at=old_date)

        old_snapshot = SystemHealthSnapshot.objects.create(
            status=HealthStatusChoices.HEALTHY,
            hostname="old-host",
            os_name="Linux-old",
            kernel_version="old-kernel",
            uptime_seconds=100,
            cpu_percent=Decimal("10.00"),
            memory_percent=Decimal("20.00"),
            disk_percent=Decimal("30.00"),
            process_count=10,
            database_status=HealthStatusChoices.HEALTHY,
            redis_status=HealthStatusChoices.HEALTHY,
            celery_status=HealthStatusChoices.HEALTHY,
            celery_beat_status=HealthStatusChoices.HEALTHY,
        )
        SystemHealthSnapshot.objects.filter(id=old_snapshot.id).update(
            created_at=old_date
        )

        old_audit_log = AuditLog.objects.create(
            actor=self.admin,
            action=AuditLog.ActionChoices.SYSTEM,
            object_type="System",
            object_id="old",
            description="Old audit log",
        )
        AuditLog.objects.filter(id=old_audit_log.id).update(created_at=old_date)

        result = cleanup_old_observability_logs(days=30)

        self.assertGreaterEqual(result["deleted_request_logs"], 1)
        self.assertGreaterEqual(result["deleted_resolved_error_logs"], 1)
        self.assertGreaterEqual(result["deleted_system_health_snapshots"], 1)
        self.assertGreaterEqual(result["deleted_audit_logs"], 1)

        self.assertFalse(RequestLog.objects.filter(id=old_request_log.id).exists())
        self.assertFalse(ErrorLog.objects.filter(id=old_resolved_error.id).exists())
        self.assertTrue(ErrorLog.objects.filter(id=old_unresolved_error.id).exists())
        self.assertFalse(
            SystemHealthSnapshot.objects.filter(id=old_snapshot.id).exists()
        )
        self.assertFalse(AuditLog.objects.filter(id=old_audit_log.id).exists())


class ObservabilityMiddlewareTestCase(ObservabilityTestMixin, APITestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = self.create_admin_user()

    def test_request_log_middleware_creates_request_log_and_sets_request_id(self):
        def get_response(request):
            return HttpResponse("OK", status=200)

        middleware = RequestLogMiddleware(get_response)

        request = self.factory.get(
            "/api/middleware-test/",
            HTTP_USER_AGENT="pytest",
            REMOTE_ADDR="127.0.0.1",
        )
        request.user = self.admin

        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Request-ID", response)

        request_log = RequestLog.objects.get(
            path="/api/middleware-test/",
        )

        self.assertEqual(request_log.user, self.admin)
        self.assertEqual(request_log.method, "GET")
        self.assertEqual(request_log.status_code, 200)
        self.assertEqual(request_log.request_id, response["X-Request-ID"])

    def test_request_log_middleware_process_exception_creates_error_log(self):
        def get_response(request):
            return HttpResponse("OK", status=200)

        middleware = RequestLogMiddleware(get_response)

        request = self.factory.get(
            "/api/middleware-error/",
            HTTP_USER_AGENT="pytest",
            REMOTE_ADDR="127.0.0.1",
        )
        request.user = self.admin
        request.observability_request_id = "middleware-error-request-id"

        try:
            raise RuntimeError("Middleware test error")
        except RuntimeError as exc:
            response = middleware.process_exception(request, exc)

        self.assertIsNone(response)

        error_log = ErrorLog.objects.get(
            exception_type="RuntimeError",
        )

        self.assertEqual(error_log.message, "Middleware test error")
        self.assertEqual(error_log.path, "/api/middleware-error/")


class ObservabilityCelerySignalTestCase(APITestCase):
    class DummyTask:
        name = "apps.observability.tasks.collect_observability_health_snapshot"

    def test_celery_task_started_signal_creates_task_log(self):
        task_id = "signal-task-started"

        log_task_started(
            sender=self.DummyTask(),
            task_id=task_id,
        )

        task_log = CeleryTaskLog.objects.get(task_id=task_id)

        self.assertEqual(task_log.task_name, self.DummyTask.name)
        self.assertEqual(task_log.status, CeleryTaskLog.StatusChoices.STARTED)
        self.assertIsNotNone(task_log.started_at)

    def test_celery_task_finished_signal_updates_task_log_success(self):
        task_id = "signal-task-success"

        log_task_started(
            sender=self.DummyTask(),
            task_id=task_id,
        )

        log_task_finished(
            sender=self.DummyTask(),
            task_id=task_id,
            retval={"status": "healthy"},
            state="SUCCESS",
        )

        task_log = CeleryTaskLog.objects.get(task_id=task_id)

        self.assertEqual(task_log.status, CeleryTaskLog.StatusChoices.SUCCESS)
        self.assertIsNotNone(task_log.finished_at)
        self.assertIsNotNone(task_log.duration_ms)
        self.assertIn("healthy", task_log.result_summary)
        self.assertEqual(task_log.error_message, "")

    def test_celery_task_finished_signal_updates_task_log_failure(self):
        task_id = "signal-task-failure"

        log_task_started(
            sender=self.DummyTask(),
            task_id=task_id,
        )

        log_task_finished(
            sender=self.DummyTask(),
            task_id=task_id,
            retval=RuntimeError("Task failed"),
            state="FAILURE",
        )

        task_log = CeleryTaskLog.objects.get(task_id=task_id)

        self.assertEqual(task_log.status, CeleryTaskLog.StatusChoices.FAILURE)
        self.assertIsNotNone(task_log.finished_at)
        self.assertIn("Task failed", task_log.error_message)


class ObservabilityManagementCommandTestCase(APITestCase):
    def test_setup_observability_scheduler_command_creates_periodic_task(self):
        call_command("setup_observability_scheduler")

        task = PeriodicTask.objects.get(
            name="Collect observability health snapshot",
        )

        self.assertTrue(task.enabled)
        self.assertEqual(
            task.task,
            "apps.observability.tasks.collect_observability_health_snapshot",
        )
        self.assertEqual(task.interval.every, 5)
        self.assertEqual(task.interval.period, IntervalSchedule.MINUTES)

    def test_cleanup_observability_logs_command(self):
        old_date = timezone.now() - timedelta(days=40)

        request_log = RequestLog.objects.create(
            method="GET",
            path="/api/old-command-log/",
            status_code=200,
            duration_ms=10,
        )
        RequestLog.objects.filter(id=request_log.id).update(created_at=old_date)

        call_command("cleanup_observability_logs", "--days", "30")

        self.assertFalse(RequestLog.objects.filter(id=request_log.id).exists())