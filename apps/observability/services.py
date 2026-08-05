import hashlib
import os
import platform
import socket
import time
import traceback as traceback_module
from datetime import timedelta
from decimal import Decimal

import psutil
import redis
from celery import current_app
from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from apps.observability.models import (
    AuditLog,
    ErrorLog,
    HealthStatusChoices,
    ObservabilityAlert,
    RequestLog,
    SeverityChoices,
    SystemHealthSnapshot,
)


def decimal_value(value):
    if value is None:
        return None

    return Decimal(str(round(float(value), 2)))


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")


def should_skip_observability_path(path):
    excluded_prefixes = getattr(
        settings,
        "OBSERVABILITY_EXCLUDED_PATH_PREFIXES",
        [],
    )

    return any(path.startswith(prefix) for prefix in excluded_prefixes)


def build_error_fingerprint(exception_type, path, message):
    raw_value = f"{exception_type}:{path}:{message[:200]}"
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


def create_request_log(
    *,
    request,
    response,
    duration_ms,
    request_id="",
):
    path = request.path

    if should_skip_observability_path(path):
        return None

    user = getattr(request, "user", None)

    if not getattr(user, "is_authenticated", False):
        user = None

    response_size = None

    if hasattr(response, "content"):
        try:
            response_size = len(response.content)
        except Exception:
            response_size = None

    return RequestLog.objects.create(
        user=user,
        request_id=request_id,
        method=request.method,
        path=path,
        query_string=request.META.get("QUERY_STRING", ""),
        status_code=getattr(response, "status_code", 0),
        duration_ms=duration_ms,
        ip_address=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        response_size_bytes=response_size,
        metadata={
            "view": getattr(request, "resolver_match", None).view_name
            if getattr(request, "resolver_match", None)
            else "",
        },
    )


def create_error_log_from_exception(
    *,
    request,
    exception,
    request_log=None,
):
    path = getattr(request, "path", "")

    if should_skip_observability_path(path):
        return None

    user = getattr(request, "user", None)

    if not getattr(user, "is_authenticated", False):
        user = None

    exception_type = exception.__class__.__name__
    message = str(exception)
    traceback_text = traceback_module.format_exc()

    fingerprint = build_error_fingerprint(
        exception_type=exception_type,
        path=path,
        message=message,
    )

    error_log = ErrorLog.objects.create(
        request_log=request_log,
        user=user,
        severity=SeverityChoices.ERROR,
        exception_type=exception_type,
        message=message,
        traceback=traceback_text[-10000:],
        method=getattr(request, "method", ""),
        path=path,
        status_code=500,
        ip_address=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        fingerprint=fingerprint,
        metadata={
            "request_id": getattr(request, "observability_request_id", ""),
        },
    )

    create_or_update_alert(
        alert_type=ObservabilityAlert.AlertTypeChoices.ERROR_SPIKE,
        severity=SeverityChoices.ERROR,
        title=f"Unhandled exception: {exception_type}",
        message=f"{message} on {path}",
        source="django",
        fingerprint=f"error:{fingerprint}",
        related_object_type="ErrorLog",
        related_object_id=str(error_log.id),
        metadata={
            "exception_type": exception_type,
            "path": path,
            "error_log_id": str(error_log.id),
        },
    )

    return error_log


def create_audit_log(
    *,
    actor=None,
    action,
    description,
    object_type="",
    object_id="",
    request=None,
    metadata=None,
):
    ip_address = None
    user_agent = ""

    if request:
        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")

    return AuditLog.objects.create(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id else "",
        description=description,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata or {},
    )


def check_database_health():
    started_at = time.monotonic()

    try:
        connection.ensure_connection()

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        latency_ms = int((time.monotonic() - started_at) * 1000)

        return {
            "status": HealthStatusChoices.HEALTHY,
            "latency_ms": latency_ms,
            "error": "",
        }

    except Exception as exc:
        latency_ms = int((time.monotonic() - started_at) * 1000)

        return {
            "status": HealthStatusChoices.UNHEALTHY,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


def check_redis_health():
    started_at = time.monotonic()

    try:
        client = redis.Redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()

        latency_ms = int((time.monotonic() - started_at) * 1000)

        return {
            "status": HealthStatusChoices.HEALTHY,
            "latency_ms": latency_ms,
            "error": "",
        }

    except Exception as exc:
        latency_ms = int((time.monotonic() - started_at) * 1000)

        return {
            "status": HealthStatusChoices.UNHEALTHY,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


def check_celery_worker_health():
    try:
        inspector = current_app.control.inspect(timeout=1)
        ping_result = inspector.ping()

        if ping_result:
            return {
                "status": HealthStatusChoices.HEALTHY,
                "workers": ping_result,
                "error": "",
            }

        return {
            "status": HealthStatusChoices.UNHEALTHY,
            "workers": {},
            "error": "No Celery workers responded.",
        }

    except Exception as exc:
        return {
            "status": HealthStatusChoices.UNHEALTHY,
            "workers": {},
            "error": str(exc),
        }


def check_celery_beat_health():
    try:
        task = PeriodicTask.objects.filter(
            name="Collect observability health snapshot",
            enabled=True,
        ).first()

        if not task:
            return {
                "status": HealthStatusChoices.UNKNOWN,
                "last_run_at": None,
                "error": "Periodic health snapshot task is not configured.",
            }

        if not task.last_run_at:
            return {
                "status": HealthStatusChoices.UNKNOWN,
                "last_run_at": None,
                "error": "Periodic health snapshot task has not run yet.",
            }

        max_age_minutes = 10
        age = timezone.now() - task.last_run_at

        if age <= timedelta(minutes=max_age_minutes):
            return {
                "status": HealthStatusChoices.HEALTHY,
                "last_run_at": task.last_run_at,
                "error": "",
            }

        return {
            "status": HealthStatusChoices.UNHEALTHY,
            "last_run_at": task.last_run_at,
            "error": "Celery Beat health task is stale.",
        }

    except Exception as exc:
        return {
            "status": HealthStatusChoices.UNKNOWN,
            "last_run_at": None,
            "error": str(exc),
        }


def get_linux_system_metrics():
    boot_time = psutil.boot_time()
    uptime_seconds = int(time.time() - boot_time)

    try:
        load_average = os.getloadavg()
    except OSError:
        load_average = (None, None, None)

    disk_path = getattr(settings, "OBSERVABILITY_DISK_PATH", "/")
    disk_usage = psutil.disk_usage(disk_path)

    memory = psutil.virtual_memory()

    return {
        "hostname": socket.gethostname(),
        "os_name": platform.platform(),
        "kernel_version": platform.release(),
        "uptime_seconds": uptime_seconds,
        "load_average_1m": decimal_value(load_average[0]),
        "load_average_5m": decimal_value(load_average[1]),
        "load_average_15m": decimal_value(load_average[2]),
        "cpu_percent": decimal_value(psutil.cpu_percent(interval=0.1)),
        "memory_percent": decimal_value(memory.percent),
        "disk_percent": decimal_value(disk_usage.percent),
        "process_count": len(psutil.pids()),
    }


def calculate_overall_health_status(
    *,
    database_status,
    redis_status,
    celery_status,
    cpu_percent,
    memory_percent,
    disk_percent,
):
    unhealthy_statuses = {
        HealthStatusChoices.UNHEALTHY,
    }

    if (
        database_status in unhealthy_statuses
        or redis_status in unhealthy_statuses
        or celery_status in unhealthy_statuses
    ):
        return HealthStatusChoices.UNHEALTHY

    cpu_warning = Decimal(
        str(getattr(settings, "OBSERVABILITY_CPU_WARNING_PERCENT", 90))
    )
    memory_warning = Decimal(
        str(getattr(settings, "OBSERVABILITY_MEMORY_WARNING_PERCENT", 90))
    )
    disk_warning = Decimal(
        str(getattr(settings, "OBSERVABILITY_DISK_WARNING_PERCENT", 85))
    )

    if (
        cpu_percent is not None
        and cpu_percent >= cpu_warning
    ):
        return HealthStatusChoices.DEGRADED

    if (
        memory_percent is not None
        and memory_percent >= memory_warning
    ):
        return HealthStatusChoices.DEGRADED

    if (
        disk_percent is not None
        and disk_percent >= disk_warning
    ):
        return HealthStatusChoices.DEGRADED

    return HealthStatusChoices.HEALTHY


def collect_system_health_snapshot():
    system_metrics = get_linux_system_metrics()
    database_health = check_database_health()
    redis_health = check_redis_health()
    celery_health = check_celery_worker_health()
    celery_beat_health = check_celery_beat_health()

    overall_status = calculate_overall_health_status(
        database_status=database_health["status"],
        redis_status=redis_health["status"],
        celery_status=celery_health["status"],
        cpu_percent=system_metrics["cpu_percent"],
        memory_percent=system_metrics["memory_percent"],
        disk_percent=system_metrics["disk_percent"],
    )

    snapshot = SystemHealthSnapshot.objects.create(
        status=overall_status,
        hostname=system_metrics["hostname"],
        os_name=system_metrics["os_name"],
        kernel_version=system_metrics["kernel_version"],
        uptime_seconds=system_metrics["uptime_seconds"],
        load_average_1m=system_metrics["load_average_1m"],
        load_average_5m=system_metrics["load_average_5m"],
        load_average_15m=system_metrics["load_average_15m"],
        cpu_percent=system_metrics["cpu_percent"],
        memory_percent=system_metrics["memory_percent"],
        disk_percent=system_metrics["disk_percent"],
        process_count=system_metrics["process_count"],
        database_status=database_health["status"],
        database_latency_ms=database_health["latency_ms"],
        redis_status=redis_health["status"],
        redis_latency_ms=redis_health["latency_ms"],
        celery_status=celery_health["status"],
        celery_beat_status=celery_beat_health["status"],
        metadata={
            "database_error": database_health["error"],
            "redis_error": redis_health["error"],
            "celery_error": celery_health["error"],
            "celery_workers": celery_health.get("workers", {}),
            "celery_beat_error": celery_beat_health["error"],
            "celery_beat_last_run_at": str(
                celery_beat_health.get("last_run_at") or ""
            ),
        },
    )

    evaluate_observability_alert_rules(snapshot)

    return snapshot


def create_or_update_alert(
    *,
    alert_type,
    severity,
    title,
    message,
    source,
    fingerprint,
    related_object_type="",
    related_object_id="",
    metadata=None,
):
    alert = ObservabilityAlert.objects.filter(
        fingerprint=fingerprint,
        status=ObservabilityAlert.StatusChoices.OPEN,
    ).first()

    if alert:
        alert.severity = severity
        alert.title = title
        alert.message = message
        alert.source = source
        alert.related_object_type = related_object_type
        alert.related_object_id = related_object_id
        alert.metadata = metadata or {}
        alert.save(
            update_fields=[
                "severity",
                "title",
                "message",
                "source",
                "related_object_type",
                "related_object_id",
                "metadata",
                "updated_at",
            ]
        )
        return alert

    return ObservabilityAlert.objects.create(
        alert_type=alert_type,
        severity=severity,
        status=ObservabilityAlert.StatusChoices.OPEN,
        title=title,
        message=message,
        source=source,
        fingerprint=fingerprint,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        metadata=metadata or {},
    )


def evaluate_observability_alert_rules(snapshot):
    cpu_warning = Decimal(
        str(getattr(settings, "OBSERVABILITY_CPU_WARNING_PERCENT", 90))
    )
    memory_warning = Decimal(
        str(getattr(settings, "OBSERVABILITY_MEMORY_WARNING_PERCENT", 90))
    )
    disk_warning = Decimal(
        str(getattr(settings, "OBSERVABILITY_DISK_WARNING_PERCENT", 85))
    )

    if snapshot.cpu_percent is not None and snapshot.cpu_percent >= cpu_warning:
        create_or_update_alert(
            alert_type=ObservabilityAlert.AlertTypeChoices.CPU_USAGE,
            severity=SeverityChoices.WARNING,
            title="High CPU usage detected",
            message=f"CPU usage is {snapshot.cpu_percent}%.",
            source="linux",
            fingerprint="linux:cpu:high",
            related_object_type="SystemHealthSnapshot",
            related_object_id=str(snapshot.id),
            metadata={"cpu_percent": str(snapshot.cpu_percent)},
        )

    if (
        snapshot.memory_percent is not None
        and snapshot.memory_percent >= memory_warning
    ):
        create_or_update_alert(
            alert_type=ObservabilityAlert.AlertTypeChoices.MEMORY_USAGE,
            severity=SeverityChoices.WARNING,
            title="High memory usage detected",
            message=f"Memory usage is {snapshot.memory_percent}%.",
            source="linux",
            fingerprint="linux:memory:high",
            related_object_type="SystemHealthSnapshot",
            related_object_id=str(snapshot.id),
            metadata={"memory_percent": str(snapshot.memory_percent)},
        )

    if snapshot.disk_percent is not None and snapshot.disk_percent >= disk_warning:
        create_or_update_alert(
            alert_type=ObservabilityAlert.AlertTypeChoices.DISK_USAGE,
            severity=SeverityChoices.WARNING,
            title="High disk usage detected",
            message=f"Disk usage is {snapshot.disk_percent}%.",
            source="linux",
            fingerprint="linux:disk:high",
            related_object_type="SystemHealthSnapshot",
            related_object_id=str(snapshot.id),
            metadata={"disk_percent": str(snapshot.disk_percent)},
        )

    service_checks = [
        (
            snapshot.database_status,
            ObservabilityAlert.AlertTypeChoices.DATABASE,
            "database:unhealthy",
            "Database health check failed",
            "postgresql",
        ),
        (
            snapshot.redis_status,
            ObservabilityAlert.AlertTypeChoices.REDIS,
            "redis:unhealthy",
            "Redis health check failed",
            "redis",
        ),
        (
            snapshot.celery_status,
            ObservabilityAlert.AlertTypeChoices.CELERY,
            "celery:worker:unhealthy",
            "Celery worker health check failed",
            "celery",
        ),
        (
            snapshot.celery_beat_status,
            ObservabilityAlert.AlertTypeChoices.CELERY_BEAT,
            "celery:beat:unhealthy",
            "Celery Beat health check failed",
            "celery",
        ),
    ]

    for service_status, alert_type, fingerprint, title, source in service_checks:
        if service_status == HealthStatusChoices.UNHEALTHY:
            create_or_update_alert(
                alert_type=alert_type,
                severity=SeverityChoices.ERROR,
                title=title,
                message=f"{title}. Check the latest system health snapshot.",
                source=source,
                fingerprint=fingerprint,
                related_object_type="SystemHealthSnapshot",
                related_object_id=str(snapshot.id),
                metadata={"snapshot_id": str(snapshot.id)},
            )

    evaluate_error_spike_alert()
    evaluate_slow_request_alert()


def evaluate_error_spike_alert():
    window_minutes = getattr(
        settings,
        "OBSERVABILITY_ERROR_SPIKE_WINDOW_MINUTES",
        10,
    )
    threshold = getattr(
        settings,
        "OBSERVABILITY_ERROR_SPIKE_THRESHOLD",
        5,
    )

    since = timezone.now() - timedelta(minutes=window_minutes)

    errors_count = ErrorLog.objects.filter(
        created_at__gte=since,
        is_resolved=False,
    ).count()

    if errors_count >= threshold:
        create_or_update_alert(
            alert_type=ObservabilityAlert.AlertTypeChoices.ERROR_SPIKE,
            severity=SeverityChoices.CRITICAL,
            title="Error spike detected",
            message=f"{errors_count} unresolved errors in the last {window_minutes} minutes.",
            source="django",
            fingerprint="django:error-spike",
            metadata={
                "errors_count": errors_count,
                "window_minutes": window_minutes,
            },
        )


def evaluate_slow_request_alert():
    threshold_ms = getattr(
        settings,
        "OBSERVABILITY_SLOW_REQUEST_THRESHOLD_MS",
        1000,
    )

    since = timezone.now() - timedelta(minutes=10)

    slow_requests_count = RequestLog.objects.filter(
        created_at__gte=since,
        duration_ms__gte=threshold_ms,
    ).count()

    if slow_requests_count >= 5:
        create_or_update_alert(
            alert_type=ObservabilityAlert.AlertTypeChoices.SLOW_REQUEST,
            severity=SeverityChoices.WARNING,
            title="Slow API requests detected",
            message=f"{slow_requests_count} slow requests in the last 10 minutes.",
            source="django",
            fingerprint="django:slow-requests",
            metadata={
                "slow_requests_count": slow_requests_count,
                "threshold_ms": threshold_ms,
            },
        )


def cleanup_old_observability_logs(days=30):
    cutoff = timezone.now() - timedelta(days=days)

    deleted_request_logs, _ = RequestLog.objects.filter(
        created_at__lt=cutoff,
    ).delete()

    deleted_error_logs, _ = ErrorLog.objects.filter(
        created_at__lt=cutoff,
        is_resolved=True,
    ).delete()

    deleted_snapshots, _ = SystemHealthSnapshot.objects.filter(
        created_at__lt=cutoff,
    ).delete()

    deleted_audit_logs, _ = AuditLog.objects.filter(
        created_at__lt=cutoff,
    ).delete()

    return {
        "deleted_request_logs": deleted_request_logs,
        "deleted_resolved_error_logs": deleted_error_logs,
        "deleted_system_health_snapshots": deleted_snapshots,
        "deleted_audit_logs": deleted_audit_logs,
    }