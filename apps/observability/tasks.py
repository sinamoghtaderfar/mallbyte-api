from celery import shared_task

from apps.observability.services import (
    cleanup_old_observability_logs,
    collect_system_health_snapshot,
)


@shared_task
def collect_observability_health_snapshot():
    snapshot = collect_system_health_snapshot()

    return {
        "snapshot_id": str(snapshot.id),
        "status": snapshot.status,
        "cpu_percent": str(snapshot.cpu_percent),
        "memory_percent": str(snapshot.memory_percent),
        "disk_percent": str(snapshot.disk_percent),
        "database_status": snapshot.database_status,
        "redis_status": snapshot.redis_status,
        "celery_status": snapshot.celery_status,
        "celery_beat_status": snapshot.celery_beat_status,
    }


@shared_task
def cleanup_observability_logs(days=30):
    return cleanup_old_observability_logs(days=days)