"""Snapshot and persist reconciliation findings; NEVER modify financial ledger."""
import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.settlements.monitoring_models import FinancialAuditAlert, FinancialAuditRun
from apps.settlements.reconciliation import reconciliation_report

logger = logging.getLogger(__name__)


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

    # Acquire a unique execution key before the potentially expensive audit.
    with transaction.atomic():
        run, created = FinancialAuditRun.objects.get_or_create(
            run_key=run_key,
            defaults={"source": source, "status": FinancialAuditRun.Status.RUNNING},
        )
    if not created:
        if run.source != source:
            raise ValidationError("Audit key is already assigned to another source.")
        return run, False

    try:
        report = reconciliation_report(sample_limit=sample_limit)
    except Exception as exc:
        # Store a sanitized error; no exception payload or PII in public API.
        logger.exception("Financial audit run %s failed", run.pk)
        run.status = FinancialAuditRun.Status.ERROR
        run.error = exc.__class__.__name__
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at"])
        return run, True

    now = timezone.now()
    new_alert_codes = []
    with transaction.atomic():
        # Serialize updates of known codes with row locks. Unique(code) covers
        # simultaneous tasks; normally daily dedupe prevents concurrency.
        run = FinancialAuditRun.objects.select_for_update().get(pk=run.pk)
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
