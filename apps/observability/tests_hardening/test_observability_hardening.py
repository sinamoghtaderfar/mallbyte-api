"""New regression tests for production hardening and dashboard API contracts."""
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.observability.middleware import RequestLogMiddleware
from apps.observability.models import (
    AuditLog, ErrorLog, HealthStatusChoices, ObservabilityAlert, RequestLog,
    SystemHealthSnapshot,
)
from apps.observability.sanitization import scrub_query, scrub_text
from apps.observability.services import (
    cleanup_old_observability_logs, create_or_update_alert,
    evaluate_observability_alert_rules, get_client_ip,
)
from apps.rbac.models import Role
from apps.rbac.utils import assign_role


class ObservabilityHardeningTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.viewer = User.objects.create_user(
            email="viewer.observability@example.test", full_name="Viewer",
            password="pass12345", phone="+989123445601",
        )
        self.operator = User.objects.create_user(
            email="operator.observability@example.test", full_name="Operator",
            password="pass12345", phone="+989123445602",
        )
        self.admin = User.objects.create_user(
            email="admin.observability@example.test", full_name="Admin",
            password="pass12345", phone="+989123445603",
        )
        self.staff = User.objects.create_user(
            email="staff.observability@example.test", full_name="Staff",
            password="pass12345", phone="+989123445604",
            is_staff=True,
        )
        for user, role in [
            (self.viewer, "observability_viewer"),
            (self.operator, "observability_operator"),
            (self.admin, "observability_admin"),
        ]:
            assign_role(user, Role.objects.get(name=role))

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def test_staff_alone_is_not_authorized(self):
        self.auth(self.staff)
        self.assertEqual(self.client.get("/api/observability/stats/").status_code, 403)

    def test_viewer_can_read_stats_but_not_logs(self):
        self.auth(self.viewer)
        self.assertEqual(self.client.get("/api/observability/stats/").status_code, 200)
        self.assertEqual(self.client.get("/api/observability/request-logs/").status_code, 403)

    def test_operator_reads_logs_and_cannot_resolve_errors(self):
        self.auth(self.operator)
        self.assertEqual(self.client.get("/api/observability/request-logs/").status_code, 200)
        err = ErrorLog.objects.create(exception_type="ValueError", message="problem")
        self.assertEqual(self.client.post(f"/api/observability/error-logs/{err.pk}/resolve/").status_code, 403)

    def test_operator_can_acknowledge_alert_with_audit(self):
        self.auth(self.operator)
        alert = ObservabilityAlert.objects.create(alert_type="system", severity="warning", title="check", message="check")
        url = f"/api/observability/alerts/{alert.pk}/acknowledge/"
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 409)
        self.assertTrue(AuditLog.objects.filter(object_id=str(alert.pk)).exists())

    def test_admin_can_resolve_errors(self):
        self.auth(self.admin)
        err = ErrorLog.objects.create(exception_type="ValueError", message="safe")
        self.assertEqual(self.client.post(f"/api/observability/error-logs/{err.pk}/resolve/").status_code, 200)
        err.refresh_from_db()
        self.assertTrue(err.is_resolved)

    def test_stats_supports_windows_and_p95(self):
        self.auth(self.viewer)
        for ms in (100, 200, 800, 1600):
            RequestLog.objects.create(method="GET", path="/api/health-test/", status_code=200, duration_ms=ms)
        r = self.client.get("/api/observability/stats/?window=1h")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["requests_count"], 4)
        self.assertEqual(r.data["p95_duration_ms"], 1600)
        self.assertIn("request_trend", r.data)
        self.assertEqual(self.client.get("/api/observability/stats/?window=100y").status_code, 400)

    def test_health_is_read_only_and_reports_staleness(self):
        self.auth(self.viewer)
        self.assertEqual(self.client.get("/api/observability/health/").status_code, 503)
        old = SystemHealthSnapshot.objects.create(status=HealthStatusChoices.HEALTHY)
        SystemHealthSnapshot.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.client.get("/api/observability/health/").status_code, 200)
        self.assertEqual(SystemHealthSnapshot.objects.count(), 1)
        self.assertTrue(self.client.get("/api/observability/health/").data["is_stale"])

    def test_sensitive_request_query_is_masked(self):
        self.assertEqual(scrub_query("page=2&token=abcdef&session=secret"),
                         "page=2&token=%5BREDACTED%5D&session=%5BREDACTED%5D")
        self.assertNotIn("abcdef", scrub_query("token=abcdef"))
        self.assertNotIn("secret123", scrub_text("Bearer secret123"))

    @override_settings(OBSERVABILITY_TRUST_PROXY_HEADERS=False)
    def test_untrusted_forwarded_ip_ignored(self):
        req = RequestFactory().get("/api/test/", REMOTE_ADDR="127.0.0.1",
                                   HTTP_X_FORWARDED_FOR="192.0.2.77")
        self.assertEqual(get_client_ip(req), "127.0.0.1")

    def test_middleware_log_failure_does_not_break_response(self):
        req = RequestFactory().get("/api/demo/")
        with patch("apps.observability.middleware.create_request_log", side_effect=OSError("DB offline")):
            res = RequestLogMiddleware(lambda request: HttpResponse("okay"))(req)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res["X-Request-ID"])

    def test_acknowledged_alert_reused_then_recovered(self):
        data = dict(alert_type="redis", severity="error", title="down", message="Redis down",
                    source="redis", fingerprint="redis:unhealthy")
        alert = create_or_update_alert(**data)
        alert.acknowledge(user=self.operator)
        same = create_or_update_alert(**data)
        self.assertEqual(same.pk, alert.pk)
        self.assertEqual(same.status, ObservabilityAlert.StatusChoices.ACKNOWLEDGED)
        healthy = SystemHealthSnapshot.objects.create(status="healthy", database_status="healthy",
                  redis_status="healthy", celery_status="healthy", celery_beat_status="healthy")
        evaluate_observability_alert_rules(healthy)
        alert.refresh_from_db()
        self.assertEqual(alert.status, ObservabilityAlert.StatusChoices.RESOLVED)

    def test_audit_retention_is_separate(self):
        log = AuditLog.objects.create(action="system", description="Retained", object_type="System")
        AuditLog.objects.filter(pk=log.pk).update(created_at=timezone.now()-timedelta(days=40))
        cleanup_old_observability_logs(days=30, audit_days=365)
        self.assertTrue(AuditLog.objects.filter(pk=log.pk).exists())
