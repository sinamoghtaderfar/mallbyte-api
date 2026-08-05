from django.contrib import admin

from apps.observability.models import (
    AuditLog,
    CeleryTaskLog,
    ErrorLog,
    ObservabilityAlert,
    RequestLog,
    SystemHealthSnapshot,
)


@admin.register(RequestLog)
class RequestLogAdmin(admin.ModelAdmin):
    list_display = [
        "method",
        "path",
        "status_code",
        "duration_ms",
        "user",
        "ip_address",
        "created_at",
    ]
    list_filter = [
        "method",
        "status_code",
        "created_at",
    ]
    search_fields = [
        "path",
        "query_string",
        "ip_address",
        "user__phone",
        "user__email",
    ]
    readonly_fields = [
        "id",
        "created_at",
    ]


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = [
        "exception_type",
        "severity",
        "path",
        "status_code",
        "is_resolved",
        "created_at",
    ]
    list_filter = [
        "severity",
        "status_code",
        "is_resolved",
        "created_at",
    ]
    search_fields = [
        "exception_type",
        "message",
        "path",
        "fingerprint",
        "user__phone",
        "user__email",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "resolved_at",
    ]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = [
        "actor",
        "action",
        "object_type",
        "object_id",
        "created_at",
    ]
    list_filter = [
        "action",
        "object_type",
        "created_at",
    ]
    search_fields = [
        "description",
        "object_type",
        "object_id",
        "actor__phone",
        "actor__email",
    ]
    readonly_fields = [
        "id",
        "created_at",
    ]


@admin.register(SystemHealthSnapshot)
class SystemHealthSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        "status",
        "hostname",
        "cpu_percent",
        "memory_percent",
        "disk_percent",
        "database_status",
        "redis_status",
        "celery_status",
        "celery_beat_status",
        "created_at",
    ]
    list_filter = [
        "status",
        "database_status",
        "redis_status",
        "celery_status",
        "celery_beat_status",
        "created_at",
    ]
    readonly_fields = [
        "id",
        "created_at",
    ]


@admin.register(ObservabilityAlert)
class ObservabilityAlertAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "alert_type",
        "severity",
        "status",
        "source",
        "created_at",
    ]
    list_filter = [
        "alert_type",
        "severity",
        "status",
        "source",
        "created_at",
    ]
    search_fields = [
        "title",
        "message",
        "fingerprint",
        "source",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "acknowledged_at",
        "resolved_at",
    ]


@admin.register(CeleryTaskLog)
class CeleryTaskLogAdmin(admin.ModelAdmin):
    list_display = [
        "task_name",
        "task_id",
        "status",
        "duration_ms",
        "started_at",
        "finished_at",
    ]
    list_filter = [
        "task_name",
        "status",
        "created_at",
    ]
    search_fields = [
        "task_id",
        "task_name",
        "error_message",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
    ]