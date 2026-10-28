"""Publicly returned workflow fields deliberately omit sensitive log payloads."""
from django.conf import settings
from rest_framework import serializers
from apps.observability.models import RequestLog, ErrorLog, CeleryTaskLog
from apps.observability.workflow_models import (
    Incident, IncidentEvent, AIDiagnosis, InfrastructureOperation,
)
from apps.observability.sanitization import scrub_text


class RequestSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = RequestLog
        fields = ("id", "request_id", "method", "path", "status_code", "duration_ms",
                  "is_error", "is_slow", "created_at")


class ErrorSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorLog
        fields = ("id", "exception_type", "severity", "status_code", "path",
                  "fingerprint", "is_resolved", "created_at")


class CeleryTaskSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = CeleryTaskLog
        fields = ("id", "task_id", "task_name", "status", "queue", "duration_ms",
                  "started_at", "finished_at", "created_at")


class IncidentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Incident
        fields = ("id", "title", "description", "severity", "status", "source_error",
                  "source_alert", "created_by", "assigned_to", "resolved_at", "created_at", "updated_at")
        read_only_fields = fields


class IncidentSummarySerializer(serializers.ModelSerializer):
    """Safe projection for viewers; no raw descriptions, source IDs or timeline notes."""
    class Meta:
        model = Incident
        fields = ("id", "severity", "status", "created_at", "updated_at")
        read_only_fields = fields


class IncidentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Incident
        fields = ("title", "description", "severity", "source_error", "source_alert")
        extra_kwargs = {"description": {"required": False, "allow_blank": True}}

    def validate_title(self, value):
        value = scrub_text(value, limit=180)
        if len(value.strip()) < 5:
            raise serializers.ValidationError("At least five characters are required.")
        return value

    def validate_description(self, value):
        return scrub_text(value, limit=2000)

    def validate(self, data):
        from apps.observability.permissions import allowed
        if data.get("source_error") and not allowed(
            self.context["request"].user, "view_observability_logs"
        ):
            raise serializers.ValidationError({"source_error": "Error log access is required."})
        return data


class IncidentEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = IncidentEvent
        fields = ("id", "incident", "actor", "event_type", "note", "from_value", "to_value", "created_at")
        read_only_fields = fields


class AIDiagnosisSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIDiagnosis
        fields = ("id", "incident", "requested_by", "model_name", "response", "status", "created_at", "updated_at")
        read_only_fields = fields


class InfrastructureOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = InfrastructureOperation
        fields = ("id", "target", "status", "reason", "requested_by", "approved_by",
                  "approved_at", "expires_at", "started_at", "completed_at",
                  "result_message", "created_at")
        read_only_fields = fields


class InfrastructureOperationRequestSerializer(serializers.Serializer):
    target = serializers.ChoiceField(choices=InfrastructureOperation.Target.choices)
    reason = serializers.CharField(min_length=15, max_length=1000, trim_whitespace=True)

    def validate_target(self, value):
        allowed = getattr(settings, "OBSERVABILITY_OPS_ALLOWED_TARGETS", ["celery_worker", "celery_beat"])
        if value not in allowed:
            raise serializers.ValidationError("This target is not enabled for operational restart requests.")
        return value

    def validate_reason(self, value):
        return scrub_text(value, limit=1000)
