import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class SeverityChoices(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"
    CRITICAL = "critical", "Critical"


class HealthStatusChoices(models.TextChoices):
    HEALTHY = "healthy", "Healthy"
    DEGRADED = "degraded", "Degraded"
    UNHEALTHY = "unhealthy", "Unhealthy"
    UNKNOWN = "unknown", "Unknown"


class RequestLog(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_logs",
    )

    request_id = models.CharField(max_length=100, blank=True, db_index=True)

    method = models.CharField(max_length=10, db_index=True)
    path = models.CharField(max_length=500, db_index=True)
    query_string = models.TextField(blank=True)

    status_code = models.PositiveSmallIntegerField(db_index=True)
    duration_ms = models.PositiveIntegerField(default=0, db_index=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    response_size_bytes = models.PositiveIntegerField(null=True, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Request Log"
        verbose_name_plural = "Request Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["path", "status_code"]),
            models.Index(fields=["status_code", "-created_at"]),
            models.Index(fields=["duration_ms", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.method} {self.path} - {self.status_code}"

    @property
    def is_error(self):
        return self.status_code >= 500

    @property
    def is_slow(self):
        return self.duration_ms >= 1000


class ErrorLog(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    request_log = models.ForeignKey(
        RequestLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="error_logs",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="error_logs",
    )

    severity = models.CharField(
        max_length=20,
        choices=SeverityChoices.choices,
        default=SeverityChoices.ERROR,
        db_index=True,
    )

    exception_type = models.CharField(max_length=255, db_index=True)
    message = models.TextField()
    traceback = models.TextField(blank=True)

    method = models.CharField(max_length=10, blank=True)
    path = models.CharField(max_length=500, blank=True, db_index=True)
    status_code = models.PositiveSmallIntegerField(default=500, db_index=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    fingerprint = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="Used to group similar errors.",
    )

    is_resolved = models.BooleanField(default=False, db_index=True)

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_error_logs",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Error Log"
        verbose_name_plural = "Error Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["severity", "-created_at"]),
            models.Index(fields=["exception_type", "-created_at"]),
            models.Index(fields=["path", "-created_at"]),
            models.Index(fields=["is_resolved", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.exception_type} - {self.path}"

    def mark_resolved(self, user=None):
        self.is_resolved = True
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.save(
            update_fields=[
                "is_resolved",
                "resolved_by",
                "resolved_at",
            ]
        )


class AuditLog(models.Model):
    class ActionChoices(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        EXPORT = "export", "Export"
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"
        ASSIGN = "assign", "Assign"
        SYSTEM = "system", "System"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )

    action = models.CharField(
        max_length=30,
        choices=ActionChoices.choices,
        db_index=True,
    )

    object_type = models.CharField(max_length=120, blank=True, db_index=True)
    object_id = models.CharField(max_length=120, blank=True, db_index=True)

    description = models.TextField()

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.action} - {self.object_type}:{self.object_id}"


class SystemHealthSnapshot(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    status = models.CharField(
        max_length=20,
        choices=HealthStatusChoices.choices,
        default=HealthStatusChoices.UNKNOWN,
        db_index=True,
    )

    hostname = models.CharField(max_length=255, blank=True)
    os_name = models.CharField(max_length=255, blank=True)
    kernel_version = models.CharField(max_length=255, blank=True)

    uptime_seconds = models.PositiveBigIntegerField(default=0)

    load_average_1m = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )
    load_average_5m = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )
    load_average_15m = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )

    cpu_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        db_index=True,
    )

    memory_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        db_index=True,
    )

    disk_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        db_index=True,
    )

    process_count = models.PositiveIntegerField(default=0)

    database_status = models.CharField(
        max_length=20,
        choices=HealthStatusChoices.choices,
        default=HealthStatusChoices.UNKNOWN,
    )
    database_latency_ms = models.PositiveIntegerField(null=True, blank=True)

    redis_status = models.CharField(
        max_length=20,
        choices=HealthStatusChoices.choices,
        default=HealthStatusChoices.UNKNOWN,
    )
    redis_latency_ms = models.PositiveIntegerField(null=True, blank=True)

    celery_status = models.CharField(
        max_length=20,
        choices=HealthStatusChoices.choices,
        default=HealthStatusChoices.UNKNOWN,
    )

    celery_beat_status = models.CharField(
        max_length=20,
        choices=HealthStatusChoices.choices,
        default=HealthStatusChoices.UNKNOWN,
    )

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "System Health Snapshot"
        verbose_name_plural = "System Health Snapshots"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["cpu_percent", "-created_at"]),
            models.Index(fields=["memory_percent", "-created_at"]),
            models.Index(fields=["disk_percent", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.status} - {self.created_at:%Y-%m-%d %H:%M:%S}"


class ObservabilityAlert(models.Model):
    class AlertTypeChoices(models.TextChoices):
        SYSTEM = "system", "System"
        DATABASE = "database", "Database"
        REDIS = "redis", "Redis"
        CELERY = "celery", "Celery"
        CELERY_BEAT = "celery_beat", "Celery Beat"
        ERROR_SPIKE = "error_spike", "Error Spike"
        SLOW_REQUEST = "slow_request", "Slow Request"
        DISK_USAGE = "disk_usage", "Disk Usage"
        MEMORY_USAGE = "memory_usage", "Memory Usage"
        CPU_USAGE = "cpu_usage", "CPU Usage"
        SCHEDULED_REPORT = "scheduled_report", "Scheduled Report"

    class StatusChoices(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    alert_type = models.CharField(
        max_length=40,
        choices=AlertTypeChoices.choices,
        db_index=True,
    )

    severity = models.CharField(
        max_length=20,
        choices=SeverityChoices.choices,
        default=SeverityChoices.WARNING,
        db_index=True,
    )

    status = models.CharField(
        max_length=30,
        choices=StatusChoices.choices,
        default=StatusChoices.OPEN,
        db_index=True,
    )

    title = models.CharField(max_length=255)
    message = models.TextField()

    source = models.CharField(
        max_length=120,
        blank=True,
        help_text="Example: linux, redis, celery, django",
    )

    fingerprint = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="Used to avoid duplicate open alerts.",
    )

    related_object_type = models.CharField(max_length=120, blank=True)
    related_object_id = models.CharField(max_length=120, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_observability_alerts",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_observability_alerts",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Observability Alert"
        verbose_name_plural = "Observability Alerts"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "severity"]),
            models.Index(fields=["alert_type", "-created_at"]),
            models.Index(fields=["fingerprint", "status"]),
        ]

    def __str__(self):
        return f"{self.severity} - {self.title}"

    def acknowledge(self, user=None):
        self.status = self.StatusChoices.ACKNOWLEDGED
        self.acknowledged_by = user
        self.acknowledged_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "acknowledged_by",
                "acknowledged_at",
                "updated_at",
            ]
        )

    def resolve(self, user=None):
        self.status = self.StatusChoices.RESOLVED
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )


class CeleryTaskLog(models.Model):
    class StatusChoices(models.TextChoices):
        STARTED = "started", "Started"
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"
        RETRY = "retry", "Retry"
        REVOKED = "revoked", "Revoked"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    task_id = models.CharField(max_length=255, unique=True, db_index=True)
    task_name = models.CharField(max_length=255, db_index=True)

    status = models.CharField(
        max_length=30,
        choices=StatusChoices.choices,
        default=StatusChoices.UNKNOWN,
        db_index=True,
    )

    queue = models.CharField(max_length=120, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    result_summary = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    traceback = models.TextField(blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Celery Task Log"
        verbose_name_plural = "Celery Task Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["task_name", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.task_name} - {self.status}"