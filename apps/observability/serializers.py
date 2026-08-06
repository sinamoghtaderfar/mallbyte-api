from rest_framework import serializers

from apps.observability.models import (
    AuditLog,
    CeleryTaskLog,
    ErrorLog,
    ObservabilityAlert,
    RequestLog,
    SystemHealthSnapshot,
)


class RequestLogSerializer(serializers.ModelSerializer):
    user_display = serializers.SerializerMethodField()

    class Meta:
        model = RequestLog
        fields = [
            "id",
            "user",
            "user_display",
            "request_id",
            "method",
            "path",
            "query_string",
            "status_code",
            "duration_ms",
            "ip_address",
            "user_agent",
            "response_size_bytes",
            "metadata",
            "is_error",
            "is_slow",
            "created_at",
        ]
        read_only_fields = fields

    def get_user_display(self, obj):
        if not obj.user:
            return None

        return obj.user.full_name or obj.user.email or str(obj.user_id)


class ErrorLogSerializer(serializers.ModelSerializer):
    user_display = serializers.SerializerMethodField()
    resolved_by_display = serializers.SerializerMethodField()

    class Meta:
        model = ErrorLog
        fields = [
            "id",
            "request_log",
            "user",
            "user_display",
            "severity",
            "exception_type",
            "message",
            "traceback",
            "method",
            "path",
            "status_code",
            "ip_address",
            "user_agent",
            "fingerprint",
            "is_resolved",
            "resolved_by",
            "resolved_by_display",
            "resolved_at",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields

    def get_user_display(self, obj):
        if not obj.user:
            return None

        return obj.user.full_name or obj.user.email or str(obj.user_id)

    def get_resolved_by_display(self, obj):
        if not obj.resolved_by:
            return None

        return (
            obj.resolved_by.full_name
            or obj.resolved_by.email
            or obj.resolved_by.phone
        )


class AuditLogSerializer(serializers.ModelSerializer):
    actor_display = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor",
            "actor_display",
            "action",
            "object_type",
            "object_id",
            "description",
            "ip_address",
            "user_agent",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields

    def get_actor_display(self, obj):
        if not obj.actor:
            return None

        return obj.actor.full_name or obj.actor.email or obj.actor.phone


class SystemHealthSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemHealthSnapshot
        fields = [
            "id",
            "status",
            "hostname",
            "os_name",
            "kernel_version",
            "uptime_seconds",
            "load_average_1m",
            "load_average_5m",
            "load_average_15m",
            "cpu_percent",
            "memory_percent",
            "disk_percent",
            "process_count",
            "database_status",
            "database_latency_ms",
            "redis_status",
            "redis_latency_ms",
            "celery_status",
            "celery_beat_status",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


class ObservabilityAlertSerializer(serializers.ModelSerializer):
    acknowledged_by_display = serializers.SerializerMethodField()
    resolved_by_display = serializers.SerializerMethodField()

    class Meta:
        model = ObservabilityAlert
        fields = [
            "id",
            "alert_type",
            "severity",
            "status",
            "title",
            "message",
            "source",
            "fingerprint",
            "related_object_type",
            "related_object_id",
            "metadata",
            "acknowledged_by",
            "acknowledged_by_display",
            "acknowledged_at",
            "resolved_by",
            "resolved_by_display",
            "resolved_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_acknowledged_by_display(self, obj):
        if not obj.acknowledged_by:
            return None

        return (
            obj.acknowledged_by.full_name
            or obj.acknowledged_by.email
            or obj.acknowledged_by.phone
        )

    def get_resolved_by_display(self, obj):
        if not obj.resolved_by:
            return None

        return (
            obj.resolved_by.full_name
            or obj.resolved_by.email
            or obj.resolved_by.phone
        )


class CeleryTaskLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = CeleryTaskLog
        fields = [
            "id",
            "task_id",
            "task_name",
            "status",
            "queue",
            "started_at",
            "finished_at",
            "duration_ms",
            "result_summary",
            "error_message",
            "traceback",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields