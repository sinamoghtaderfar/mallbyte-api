"""Celery background tasks; none initiate or settle money movements."""
from celery import shared_task
from django.utils import timezone

from apps.settlements.monitoring import record_financial_audit


@shared_task(name="apps.settlements.tasks.run_daily_financial_audit")
def run_daily_financial_audit():
    # Stable for all workers in the configured business timezone.
    key = f"daily:{timezone.localdate().isoformat()}"
    run, created = record_financial_audit(run_key=key, source="scheduled")
    return {
        "run_id": run.pk,
        "created": created,
        "status": run.status,
        "findings_count": run.findings_count,
    }
