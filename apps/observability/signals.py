"""Best-effort task instrumentation that must never break task execution."""
import logging
from celery.signals import task_postrun, task_prerun
from django.conf import settings
from django.utils import timezone
from apps.observability.models import CeleryTaskLog
from apps.observability.sanitization import scrub_text

logger = logging.getLogger(__name__)
STATUS_MAP = {
    "SUCCESS": CeleryTaskLog.StatusChoices.SUCCESS,
    "FAILURE": CeleryTaskLog.StatusChoices.FAILURE,
    "RETRY": CeleryTaskLog.StatusChoices.RETRY,
    "REVOKED": CeleryTaskLog.StatusChoices.REVOKED,
}


@task_prerun.connect
def log_task_started(sender=None, task_id=None, task=None, **kwargs):
    if not task_id:
        return
    try:
        CeleryTaskLog.objects.update_or_create(
            task_id=task_id,
            defaults={"task_name": sender.name if sender else "",
                      "status": CeleryTaskLog.StatusChoices.STARTED,
                      "started_at": timezone.now(), "metadata": {}},
        )
    except Exception:
        logger.exception("Could not record Celery task start")


@task_postrun.connect
def log_task_finished(sender=None, task_id=None, task=None, retval=None, state=None, **kwargs):
    if not task_id:
        return
    try:
        now = timezone.now()
        name = sender.name if sender else ""
        task_log, _created = CeleryTaskLog.objects.get_or_create(
            task_id=task_id, defaults={"task_name": name, "started_at": now},
        )
        status = STATUS_MAP.get(state, CeleryTaskLog.StatusChoices.UNKNOWN)
        store = getattr(settings, "OBSERVABILITY_STORE_TASK_RESULTS", True)
        task_log.task_name = name or task_log.task_name
        task_log.status = status
        task_log.finished_at = now
        task_log.duration_ms = max(0, int((now - (task_log.started_at or now)).total_seconds() * 1000))
        task_log.result_summary = (
            scrub_text(retval, limit=2000) if store and status != CeleryTaskLog.StatusChoices.FAILURE else ""
        )
        task_log.error_message = (
            scrub_text(retval, limit=2000) if store and status == CeleryTaskLog.StatusChoices.FAILURE else ""
        )
        task_log.save(update_fields=[
            "task_name", "status", "finished_at", "duration_ms",
            "result_summary", "error_message", "updated_at",
        ])
    except Exception:
        logger.exception("Could not record Celery task completion")
