"""Durable audit leases recover failures without changing the money ledger."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from celery.exceptions import Retry
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from apps.settlements.monitoring import record_financial_audit
from apps.settlements.monitoring_models import FinancialAuditAlert, FinancialAuditRun
from apps.settlements.tasks import (
    AuditUnavailable,
    recover_financial_audits,
    run_daily_financial_audit,
    run_manual_financial_audit,
)

CLEAN = {"findings": {"check": {"count": 0}}, "total_findings": 0}
WARNING = {"findings": {"check": {"count": 1}}, "total_findings": 1}


@override_settings(FINANCIAL_AUDIT_MAX_ATTEMPTS=4, FINANCIAL_AUDIT_LEASE_SECONDS=60)
class AuditRecoveryTests(TestCase):
    def test_failure_retries_same_run_and_keeps_sanitized_error(self):
        with patch("apps.settlements.monitoring.reconciliation_report", side_effect=RuntimeError("private detail")):
            first, _ = record_financial_audit(run_key="manual:retry")
        self.assertEqual(first.error, "RuntimeError")
        self.assertEqual(first.attempts, 1)
        with patch("apps.settlements.monitoring.reconciliation_report", return_value=CLEAN):
            retry, executed = record_financial_audit(run_key="manual:retry")
        self.assertTrue(executed)
        self.assertEqual(retry.pk, first.pk)
        self.assertEqual(retry.attempts, 2)
        self.assertEqual(retry.status, "clean")
        self.assertEqual(retry.error, "")

    def test_fresh_worker_is_not_reexecuted_and_stale_worker_is_reclaimed(self):
        run = FinancialAuditRun.objects.create(
            run_key="manual:lease", source="manual", started_at=timezone.now(), attempts=1,
        )
        with patch("apps.settlements.monitoring.reconciliation_report", return_value=CLEAN) as report:
            _, executed = record_financial_audit(run_key=run.run_key)
            self.assertFalse(executed)
            report.assert_not_called()
            FinancialAuditRun.objects.filter(pk=run.pk).update(started_at=timezone.now() - timedelta(minutes=2))
            reclaimed, executed = record_financial_audit(run_key=run.run_key)
        self.assertTrue(executed)
        self.assertEqual(reclaimed.attempts, 2)

    def test_attempt_limit_stops_permanent_failure(self):
        run = FinancialAuditRun.objects.create(
            run_key="manual:exhausted", source="manual", status="error", attempts=4,
        )
        with patch("apps.settlements.monitoring.reconciliation_report") as report:
            _, executed = record_financial_audit(run_key=run.run_key)
            self.assertFalse(executed)
            report.assert_not_called()
        with self.assertRaises(AuditUnavailable):
            run_manual_financial_audit(run_key=run.run_key)

    def test_superseded_worker_cannot_publish_alerts(self):
        def abandoned_worker(*, sample_limit):
            FinancialAuditRun.objects.filter(run_key="manual:fence").update(
                started_at=timezone.now() - timedelta(minutes=2),
            )
            with patch("apps.settlements.monitoring.reconciliation_report", return_value=CLEAN):
                newer, _ = record_financial_audit(run_key="manual:fence")
            self.assertEqual(newer.attempts, 2)
            return WARNING

        with patch("apps.settlements.monitoring.reconciliation_report", side_effect=abandoned_worker):
            run, published = record_financial_audit(run_key="manual:fence")
        self.assertFalse(published)
        self.assertEqual(run.status, "clean")
        self.assertFalse(FinancialAuditAlert.objects.exists())

    def test_recovery_only_dispatches_failed_and_expired_runs(self):
        stale = timezone.now() - timedelta(minutes=2)
        FinancialAuditRun.objects.create(run_key="daily:failed", source="scheduled", status="error", attempts=1)
        FinancialAuditRun.objects.create(run_key="manual:stale", source="manual", started_at=stale, attempts=1, sample_limit=7)
        FinancialAuditRun.objects.create(run_key="manual:fresh", source="manual", started_at=timezone.now(), attempts=1)
        FinancialAuditRun.objects.create(run_key="manual:finished", source="manual", status="clean", attempts=1)
        FinancialAuditRun.objects.create(run_key="manual:exhausted", source="manual", status="error", attempts=4)
        with patch("apps.settlements.tasks.run_daily_financial_audit.delay") as daily, patch(
            "apps.settlements.tasks.run_manual_financial_audit.delay",
        ) as manual:
            self.assertEqual(recover_financial_audits(), {"queued": 2})
        daily.assert_called_once_with(run_key="daily:failed")
        manual.assert_called_once_with(run_key="manual:stale", sample_limit=7)

    def test_daily_retry_preserves_key_across_midnight(self):
        run = FinancialAuditRun.objects.create(run_key="daily:old-date", source="scheduled", status="error", attempts=1)
        with patch("apps.settlements.tasks.record_financial_audit", return_value=(run, True)), patch.object(
            run_daily_financial_audit, "retry", side_effect=Retry(),
        ) as retry:
            with self.assertRaises(Retry):
                run_daily_financial_audit(run_key=run.run_key)
        self.assertEqual(retry.call_args.kwargs["kwargs"], {"run_key": run.run_key})

    def test_schedule_installation_is_idempotent_and_disable_includes_recovery(self):
        for _ in range(2):
            call_command("install_financial_audit_schedule", stdout=StringIO())
        tasks = PeriodicTask.objects.filter(name__startswith="MallByte financial reconciliation")
        self.assertEqual(tasks.count(), 2)
        self.assertEqual(tasks.filter(enabled=True).count(), 2)
        call_command("install_financial_audit_schedule", disable=True, stdout=StringIO())
        self.assertFalse(tasks.filter(enabled=True).exists())
