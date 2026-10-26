"""Celery audit jobs; never initiate or settle real money movements."""
from celery import shared_task
from django.utils import timezone

from apps.settlements.monitoring import record_financial_audit


@shared_task(name="apps.settlements.tasks.run_daily_financial_audit")
def run_daily_financial_audit():
    key = f"daily:{timezone.localdate().isoformat()}"
    run, created = record_financial_audit(run_key=key, source="scheduled")
    return {
        "run_id": run.pk,
        "created": created,
        "status": run.status,
        "findings_count": run.findings_count,
    }


@shared_task(name="apps.settlements.tasks.run_manual_financial_audit")
def run_manual_financial_audit(run_key: str, sample_limit: int = 20):
    if not run_key.startswith("manual:"):
        raise ValueError("Only manual audit keys can use this task")
    run, created = record_financial_audit(
        run_key=run_key, source="manual", sample_limit=sample_limit,
    )
    return {
        "run_id": run.pk,
        "created": created,
        "status": run.status,
        "findings_count": run.findings_count,
    }
