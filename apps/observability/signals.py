from django.utils import timezone
from celery.signals import task_postrun, task_prerun

from apps.observability.models import CeleryTaskLog


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

    task_name = sender.name if sender else ""

    CeleryTaskLog.objects.update_or_create(
        task_id=task_id,
        defaults={
            "task_name": task_name,
            "status": CeleryTaskLog.StatusChoices.STARTED,
            "started_at": timezone.now(),
            "metadata": {},
        },
    )


@task_postrun.connect
def log_task_finished(
    sender=None,
    task_id=None,
    task=None,
    retval=None,
    state=None,
    **kwargs,
):
    if not task_id:
        return

    task_name = sender.name if sender else ""
    now = timezone.now()

    task_log, _created = CeleryTaskLog.objects.get_or_create(
        task_id=task_id,
        defaults={
            "task_name": task_name,
            "started_at": now,
        },
    )

    started_at = task_log.started_at or now
    duration_ms = int((now - started_at).total_seconds() * 1000)

    status = STATUS_MAP.get(
        state,
        CeleryTaskLog.StatusChoices.UNKNOWN,
    )

    error_message = ""
    result_summary = ""

    if status == CeleryTaskLog.StatusChoices.FAILURE:
        error_message = str(retval)[:2000]
    else:
        result_summary = str(retval)[:2000]

    task_log.task_name = task_name or task_log.task_name
    task_log.status = status
    task_log.finished_at = now
    task_log.duration_ms = duration_ms
    task_log.result_summary = result_summary
    task_log.error_message = error_message

    task_log.save(
        update_fields=[
            "task_name",
            "status",
            "finished_at",
            "duration_ms",
            "result_summary",
            "error_message",
            "updated_at",
        ]
    )