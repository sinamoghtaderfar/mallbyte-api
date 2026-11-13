"""Snapshot and persist reconciliation findings; NEVER modify financial ledger."""
import logging
from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.settlements.monitoring_models import FinancialAuditAlert, FinancialAuditRun
from apps.settlements.reconciliation import reconciliation_report

logger = logging.getLogger(__name__)


def audit_limits():
    return (
        max(1, int(getattr(settings, "FINANCIAL_AUDIT_MAX_ATTEMPTS", 4))),
        max(60, int(getattr(settings, "FINANCIAL_AUDIT_LEASE_SECONDS", 1800))),
    )


def record_financial_audit(*, run_key, source="manual", sample_limit=20):
    """Exactly one persisted result per key. Failures remain inspectable.

    Scheduled callers must use a stable daily key; manual callers use a UUID.
    The unique constraint coordinates overlapping workers on PostgreSQL.
    """
    if not run_key or len(run_key) > 96:
        raise ValidationError("Invalid audit run key.")
    if source not in FinancialAuditRun.Source.values:
        raise ValidationError("Invalid audit source.")
    if not (1 <= sample_limit <= 100):
        raise ValidationError("sample_limit must be between 1 and 100.")

    maximum, lease_seconds = audit_limits()
    now = timezone.now()
    # A short claim transaction excludes duplicates without holding a lock during
    # reconciliation. A fencing token prevents an abandoned worker overwriting
    # the result of a later lease holder.
    with transaction.atomic():
        run, created = FinancialAuditRun.objects.get_or_create(
            run_key=run_key,
            defaults={"source": source, "status": FinancialAuditRun.Status.RUNNING, "sample_limit": sample_limit},
        )
        run = FinancialAuditRun.objects.select_for_update().get(pk=run.pk)
        if run.source != source:
            raise ValidationError("Audit key is already assigned to another source.")
        if run.sample_limit != sample_limit:
            raise ValidationError("Audit key already has different inputs.")
        if not created:
            if run.status in {FinancialAuditRun.Status.CLEAN, FinancialAuditRun.Status.WARNINGS}:
                return run, False
            if run.status == FinancialAuditRun.Status.RUNNING and (run.started_at or run.created_at) > now - timedelta(seconds=lease_seconds):
                return run, False
            if run.attempts >= maximum:
                return run, False
        run.status = FinancialAuditRun.Status.RUNNING
        run.started_at, run.finished_at = now, None
        run.error = ""
        run.attempts += 1
        run.execution_token = token = uuid4()
        run.save(update_fields=["status", "started_at", "finished_at", "error", "attempts", "execution_token"])

    try:
        report = reconciliation_report(sample_limit=sample_limit)
    except Exception as exc:
        # Store a sanitized error; no exception payload or PII in public API.
        logger.exception("Financial audit run %s failed", run.pk)
        FinancialAuditRun.objects.filter(pk=run.pk, execution_token=token, status=FinancialAuditRun.Status.RUNNING).update(
            status=FinancialAuditRun.Status.ERROR, error=exc.__class__.__name__, finished_at=timezone.now(),
        )
        run.refresh_from_db()
        return run, True

    now = timezone.now()
    new_alert_codes = []
    with transaction.atomic():
        # Serialize updates of known codes with row locks. Unique(code) covers
        # simultaneous tasks; normally daily dedupe prevents concurrency.
        run = FinancialAuditRun.objects.select_for_update().get(pk=run.pk)
        if run.execution_token != token or run.status != FinancialAuditRun.Status.RUNNING:
            return run, False
        for code, finding in report["findings"].items():
            count = int(finding["count"])
            if count:
                alert, created_alert = FinancialAuditAlert.objects.select_for_update().get_or_create(
                    code=code,
                    defaults={
                        "is_open": True,
                        "findings_count": count,
                        "sample": finding,
                        "first_seen_at": now,
                        "last_seen_at": now,
                        "resolved_at": None,
                        "last_run": run,
                    },
                )
                if not created_alert:
                    was_closed = not alert.is_open
                    alert.is_open = True
                    alert.findings_count = count
                    alert.sample = finding
                    alert.last_seen_at = now
                    alert.resolved_at = None
                    alert.last_run = run
                    if was_closed:
                        alert.first_seen_at = now
                    alert.save(update_fields=["is_open", "findings_count", "sample", "last_seen_at", "resolved_at", "last_run", "first_seen_at"])
                if created_alert or (not created_alert and was_closed):
                    new_alert_codes.append(code)
            else:
                # Keep resolved issues for audit trail instead of deleting them.
                FinancialAuditAlert.objects.filter(code=code, is_open=True).update(
                    is_open=False, findings_count=0, sample={},
                    resolved_at=now, last_run=run,
                )
        run.status = (
            FinancialAuditRun.Status.WARNINGS if report["total_findings"]
            else FinancialAuditRun.Status.CLEAN
        )
        run.findings_count = int(report["total_findings"])
        run.summary = report
        run.finished_at = now
        run.save(update_fields=["status", "findings_count", "summary", "finished_at"])
    return run, True
