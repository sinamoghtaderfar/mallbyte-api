"""Persistence for automated, read-only financial audits."""
from django.db import models


class FinancialAuditRun(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        SCHEDULED = "scheduled", "Scheduled"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        CLEAN = "clean", "No findings"
        WARNINGS = "warnings", "Warnings"
        ERROR = "error", "Failed"

    id = models.BigAutoField(primary_key=True)
    run_key = models.CharField(max_length=96, unique=True)
    source = models.CharField(max_length=12, choices=Source.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    findings_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["-created_at"], name="sett_audit_run_created_idx")]


class FinancialAuditAlert(models.Model):
    """Current state of a particular reconciliation check; no customer PII."""

    id = models.BigAutoField(primary_key=True)
    code = models.CharField(max_length=100, unique=True)
    is_open = models.BooleanField(default=True)
    findings_count = models.PositiveIntegerField(default=0)
    sample = models.JSONField(default=dict)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    last_run = models.ForeignKey(
        FinancialAuditRun, on_delete=models.PROTECT, related_name="alerts"
    )

    class Meta:
        ordering = ["-last_seen_at", "code"]
        indexes = [models.Index(fields=["is_open", "-last_seen_at"], name="sett_alert_open_seen_idx")]
