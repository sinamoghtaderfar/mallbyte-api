"""Celery audit jobs; never initiate or settle real money movements."""
from datetime import timedelta

from celery import shared_task
from django.db import InterfaceError, OperationalError
from django.db.models import Q
from django.utils import timezone

from apps.settlements.monitoring import audit_limits, record_financial_audit
from apps.settlements.monitoring_models import FinancialAuditRun


class AuditUnavailable(Exception):
    """Sanitized task failure; the durable run contains diagnostic classification."""


def retry_failed_run(task, run, kwargs):
    if run.status == FinancialAuditRun.Status.ERROR:
        if run.attempts >= audit_limits()[0]:
            raise AuditUnavailable("Financial audit attempt limit reached.")
        raise task.retry(exc=AuditUnavailable("Financial audit temporarily unavailable."),
                         countdown=min(300, 30 * (2 ** task.request.retries)), kwargs=kwargs)


@shared_task(name="apps.settlements.tasks.run_daily_financial_audit", bind=True, max_retries=3,
             autoretry_for=(OperationalError, InterfaceError), retry_backoff=30, retry_backoff_max=300)
def run_daily_financial_audit(self, run_key=None):
    key = run_key or f"daily:{timezone.localdate().isoformat()}"
    if not key.startswith("daily:"):
        raise ValueError("Only daily audit keys can use this task")
    run, created = record_financial_audit(run_key=key, source="scheduled")
    retry_failed_run(self, run, {"run_key": key})
    return {
        "run_id": run.pk,
        "created": created,
        "status": run.status,
        "findings_count": run.findings_count,
    }


@shared_task(name="apps.settlements.tasks.run_manual_financial_audit", bind=True, max_retries=3,
             autoretry_for=(OperationalError, InterfaceError), retry_backoff=30, retry_backoff_max=300)
def run_manual_financial_audit(self, run_key: str, sample_limit: int = 20):
    if not run_key.startswith("manual:"):
        raise ValueError("Only manual audit keys can use this task")
    run, created = record_financial_audit(
        run_key=run_key, source="manual", sample_limit=sample_limit,
    )
    retry_failed_run(self, run, {"run_key": run_key, "sample_limit": sample_limit})
    return {
        "run_id": run.pk,
        "created": created,
        "status": run.status,
        "findings_count": run.findings_count,
    }


@shared_task(name="apps.settlements.tasks.recover_financial_audits", autoretry_for=(OperationalError, InterfaceError),
             retry_backoff=30, max_retries=3)
def recover_financial_audits():
    maximum, lease_seconds = audit_limits()
    cutoff = timezone.now() - timedelta(seconds=lease_seconds)
    stale = Q(started_at__lte=cutoff) | Q(started_at__isnull=True, created_at__lte=cutoff)
    runs = FinancialAuditRun.objects.filter(attempts__lt=maximum).filter(
        Q(status=FinancialAuditRun.Status.ERROR) | (Q(status=FinancialAuditRun.Status.RUNNING) & stale)
    ).order_by("created_at")[:50]
    queued = 0
    for run in runs:
        if run.source == FinancialAuditRun.Source.SCHEDULED:
            run_daily_financial_audit.delay(run_key=run.run_key)
        else:
            run_manual_financial_audit.delay(run_key=run.run_key, sample_limit=run.sample_limit)
        queued += 1
    return {"queued": queued}
