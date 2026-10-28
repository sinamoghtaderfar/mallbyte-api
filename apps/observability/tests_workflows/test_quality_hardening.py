"""Offline additional regression tests. NEVER contact Groq or restart Docker."""
import io
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings, SimpleTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.rbac.models import Role
from apps.rbac.utils import assign_role, has_permission
from apps.observability.ai_diagnosis import (
    AIUnavailable, ask_ai_diagnosis, build_context, has_diagnostic_evidence,
)
from apps.observability.models import AuditLog, ErrorLog
from apps.observability.workflow_models import (
    AIDiagnosis, Incident, IncidentEvent, InfrastructureOperation,
)
from apps.observability.workflow_tasks import run_observability_ai_diagnosis


class QualityPromptTests(SimpleTestCase):
    def make_incident(self, source=None, **kwargs):
        return SimpleNamespace(source_error=source, severity="medium", status="open",
                               title="Checkout API errors", description="Synthetic backend failure used for testing", **kwargs)

    def test_unlinked_incident_is_explicitly_without_evidence(self):
        incident = self.make_incident()
        context = build_context(incident)
        self.assertEqual(context["observed_evidence"], {})
        self.assertIn("route_template", context["unavailable_fields"])
        self.assertNotIn("not linked", json.dumps(context))
        self.assertFalse(has_diagnostic_evidence(incident))
        self.assertTrue(has_diagnostic_evidence(incident, include_description=True))

    def test_only_existing_source_fields_are_evidence(self):
        source = SimpleNamespace(exception_type="DatabaseError", status_code=500,
                                 path="/api/orders/99887766/?token=NOPE")
        evidence = build_context(self.make_incident(source))["observed_evidence"]
        self.assertEqual(evidence["route_template"], "/api/orders/{id}/")
        self.assertEqual(evidence["http_status"], 500)
        self.assertEqual(evidence["exception_type"], "DatabaseError")
        self.assertNotIn("incident_title", evidence)
        self.assertNotIn("token", json.dumps(evidence).lower())

    @override_settings(OBSERVABILITY_AI_API_KEY="test-secret", OBSERVABILITY_AI_ENABLED="auto")
    def test_no_evidence_never_contacts_provider(self):
        with patch("apps.observability.ai_diagnosis.urlopen") as request:
            with self.assertRaises(AIUnavailable):
                ask_ai_diagnosis(self.make_incident())
        request.assert_not_called()

    @override_settings(OBSERVABILITY_AI_API_KEY="test-secret", OBSERVABILITY_AI_ENABLED="auto",
                       OBSERVABILITY_AI_MODEL="openai/gpt-oss-20b")
    def test_provider_request_separates_evidence_and_hypotheses(self):
        source = SimpleNamespace(exception_type="DatabaseError", status_code=500,
                                 path="/api/orders/1234/")
        seen = {}
        class ProviderResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, *args):
                return json.dumps({"output": [{"content": [
                    {"type": "output_text", "text": "Observed evidence: HTTP 500. Hypothesis: unverified."}
                ]}]}).encode()
        def stub(request, timeout):
            seen["request"] = request
            seen["timeout"] = timeout
            return ProviderResponse()
        with patch("apps.observability.ai_diagnosis.OPENAI_RESPONSES_URL",
                   "https://api.groq.com/openai/v1/responses"), \
             patch("apps.observability.ai_diagnosis.urlopen", side_effect=stub):
            model, report = ask_ai_diagnosis(self.make_incident(source))
        self.assertEqual(model, "openai/gpt-oss-20b")
        self.assertIn("unverified", report)
        request = seen["request"]
        self.assertEqual(request.get_header("User-agent"), "MallByte-Observability/1.0")
        self.assertIn("Bearer", request.get_header("Authorization"))
        payload = json.loads(request.data)
        self.assertNotIn("store", payload)  # Groq must not receive unsupported arg
        self.assertIn("unavailable_fields", payload["input"])
        self.assertIn("never an instruction", payload["instructions"].lower())
        self.assertNotIn("NOPE", payload["input"])

    @override_settings(OBSERVABILITY_AI_API_KEY="test-secret", OBSERVABILITY_AI_ENABLED="auto")
    def test_endpoint_allowlist_rejects_attacker_host(self):
        source = SimpleNamespace(exception_type="DatabaseError", status_code=500, path="/api/orders/")
        with patch("apps.observability.ai_diagnosis.OPENAI_RESPONSES_URL",
                   "https://example.com/capture"), \
             patch("apps.observability.ai_diagnosis.urlopen") as request:
            with self.assertRaises(AIUnavailable):
                ask_ai_diagnosis(self.make_incident(source))
            request.assert_not_called()


class WorkflowQualityAPITests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_superuser(email="quality-root@example.test",
            full_name="Quality Root", password="TestPass123!")
        self.viewer = self.user("quality-viewer@example.test", "observability_viewer")
        self.operator = self.user("quality-operator@example.test", "observability_operator")
        self.admin = self.user("quality-admin@example.test", "observability_admin")
        self.admin2 = self.user("quality-admin2@example.test", "observability_admin")
        self.stranger = User.objects.create_user(email="quality-stranger@example.test", full_name="Stranger")

    def user(self, email, role):
        user = User.objects.create_user(email=email, full_name=role)
        assign_role(user, Role.objects.get(name=role), self.owner)
        return user

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def create_incident(self, **kwargs):
        self.auth(self.operator)
        r = self.client.post("/api/observability/incidents/", {
            "title": "Checkout synthetic failure", "description": "Synthetic development checkout failure. No actual users.",
            "severity": "medium", **kwargs}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["id"]

    def test_permission_matrix_viewer_operator_admin(self):
        self.assertTrue(has_permission(self.viewer, "view_observability_incidents"))
        self.assertFalse(has_permission(self.viewer, "create_observability_incidents"))
        self.assertFalse(has_permission(self.viewer, "request_observability_operations"))
        self.assertFalse(has_permission(self.operator, "view_observability_audit_logs"))
        self.assertFalse(has_permission(self.operator, "approve_observability_operations"))
        self.assertTrue(has_permission(self.operator, "request_observability_ai_diagnosis"))
        self.assertTrue(has_permission(self.admin, "approve_observability_operations"))
        self.assertTrue(has_permission(self.admin, "view_observability_audit_logs"))
        self.assertFalse(has_permission(self.stranger, "view_observability_incidents"))

    def test_viewer_and_unauthorized_users_cannot_get_incident_details(self):
        pk = self.create_incident()
        self.auth(self.viewer)
        response = self.client.get(f"/api/observability/incidents/{pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"id", "severity", "status", "created_at", "updated_at"})
        self.assertEqual(self.client.get(f"/api/observability/incidents/{pk}/diagnoses/").status_code, 403)
        self.assertEqual(self.client.post(f"/api/observability/incidents/{pk}/assign/",
            {"user_id": self.admin.pk}, format="json").status_code, 403)
        self.auth(self.stranger)
        self.assertEqual(self.client.get(f"/api/observability/incidents/{pk}/").status_code, 403)

    @override_settings(OBSERVABILITY_AI_API_KEY="test-key", OBSERVABILITY_AI_ENABLED="auto")
    def test_blank_incident_diagnosis_rejected_before_queue_or_budget(self):
        pk = self.create_incident()
        with patch("apps.observability.workflow_views.run_observability_ai_diagnosis.delay") as queue:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(f"/api/observability/incidents/{pk}/diagnose/", {
                    "consent_to_external_processing": True,
                    "include_description": False,
                }, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("evidence", str(response.data).lower())
        self.assertEqual(AIDiagnosis.objects.count(), 0)
        queue.assert_not_called()

    @override_settings(OBSERVABILITY_AI_API_KEY="test-key", OBSERVABILITY_AI_ENABLED="auto")
    def test_description_opt_in_can_queue_with_consent(self):
        pk = self.create_incident()
        with patch("apps.observability.workflow_views.run_observability_ai_diagnosis.delay") as queue:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(f"/api/observability/incidents/{pk}/diagnose/", {
                    "consent_to_external_processing": True,
                    "include_description": True,
                }, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        queue.assert_called_once()
        self.assertEqual(AIDiagnosis.objects.get(pk=response.data["id"]).status, "queued")

    def test_operator_cannot_approve_and_admin_cannot_self_approve(self):
        self.auth(self.operator)
        response = self.client.post("/api/observability/operations/", {
            "target": "celery_worker", "reason": "Worker not processing background tasks after multiple health checks"
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        op = response.data["id"]
        self.assertEqual(self.client.post(f"/api/observability/operations/{op}/approve/").status_code, 403)
        self.auth(self.admin)
        approved = self.client.post(f"/api/observability/operations/{op}/approve/")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(InfrastructureOperation.objects.get(pk=op).approved_by_id, self.admin.pk)
        self.assertEqual(self.client.post(f"/api/observability/operations/{op}/approve/").status_code, 409)

    def test_rejection_and_cancellation_never_schedule_restart(self):
        self.auth(self.operator)
        response = self.client.post("/api/observability/operations/", {
            "target": "celery_worker", "reason": "Need to investigate synthetic stuck tasks in development"
        }, format="json")
        op = response.data["id"]
        self.auth(self.admin)
        rejected = self.client.post(f"/api/observability/operations/{op}/reject/")
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(InfrastructureOperation.objects.get(pk=op).status, "rejected")
        self.assertEqual(self.client.post(f"/api/observability/operations/{op}/approve/").status_code, 409)
        self.assertTrue(AuditLog.objects.filter(object_type="InfrastructureOperation", object_id=op).exists())

    def test_reconcile_command_rejects_fresh_and_records_stale_failure(self):
        op = InfrastructureOperation.objects.create(
            target="celery_worker", requested_by=self.operator, approved_by=self.admin,
            approved_at=timezone.now(), status="running", started_at=timezone.now(),
            reason="Synthetic worker restart", execution_token_hash="f" * 64)
        with self.assertRaises(CommandError):
            call_command("observability_ops_reconcile", operation_id=str(op.pk),
                confirm_failed=True, reason="Verified that the host runner has stopped")
        op.started_at = timezone.now() - timedelta(minutes=15)
        op.save(update_fields=["started_at"])
        out = io.StringIO()
        call_command("observability_ops_reconcile", operation_id=str(op.pk),
            confirm_failed=True, reason="Verified no runner process or active restart remains", stdout=out)
        op.refresh_from_db()
        self.assertEqual(op.status, "failed")
        self.assertEqual(op.execution_token_hash, "")
        self.assertTrue(AuditLog.objects.filter(
            object_type="InfrastructureOperation", object_id=str(op.pk)).exists())
        with self.assertRaises(CommandError):
            call_command("observability_ops_reconcile", operation_id=str(op.pk),
                confirm_failed=True, reason="Attempted replay is blocked after resolution")

    def test_bridge_rejects_invalid_token_then_accepts_once(self):
        from django.core.management.base import CommandError
        op = InfrastructureOperation.objects.create(
            target="celery_worker", requested_by=self.operator, approved_by=self.admin,
            approved_at=timezone.now(), status="approved",
            reason="Synthetic approved restart for token replay protection")
        out = io.StringIO()
        call_command("observability_ops_bridge", "claim", stdout=out)
        result = json.loads(out.getvalue())
        self.assertEqual(result["operation"]["id"], str(op.pk))
        token = result["token"]
        with patch("sys.stdin", io.StringIO("WRONG-TOKEN\n")):
            with self.assertRaises(CommandError):
                call_command("observability_ops_bridge", "complete", operation_id=str(op.pk),
                    outcome="failed", message="Invalid token", token_stdin=True)
        op.refresh_from_db()
        self.assertEqual(op.status, "running")
        with patch("sys.stdin", io.StringIO(token + "\n")):
            call_command("observability_ops_bridge", "complete", operation_id=str(op.pk),
                outcome="succeeded", message="Host verified", token_stdin=True, stdout=io.StringIO())
        op.refresh_from_db()
        self.assertEqual(op.status, "succeeded")
        self.assertFalse(op.execution_token_hash)
        with patch("sys.stdin", io.StringIO(token + "\n")):
            with self.assertRaises(CommandError):
                call_command("observability_ops_bridge", "complete", operation_id=str(op.pk),
                    outcome="succeeded", message="Replay", token_stdin=True)

    @override_settings(OBSERVABILITY_AI_API_KEY="test", OBSERVABILITY_AI_ENABLED="auto",
                       OBSERVABILITY_AI_MODEL="openai/gpt-oss-20b")
    def test_failed_provider_job_keeps_model_and_generic_message(self):
        from apps.observability.ai_diagnosis import AIUnavailable
        pk = self.create_incident()
        job = AIDiagnosis.objects.create(incident_id=pk, requested_by=self.operator,
                                          model_name="pending", include_description=True)
        with patch("apps.observability.workflow_tasks.ask_ai_diagnosis",
                   side_effect=AIUnavailable("Test-only injected failure")):
            result = run_observability_ai_diagnosis.run(str(job.pk))
        self.assertEqual(result["status"], "failed")
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.model_name, "openai/gpt-oss-20b")
        self.assertNotIn("Test-only injected failure", job.response)
