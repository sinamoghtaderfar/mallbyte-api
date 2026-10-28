"""Permission classes enforce policy on every endpoint, not just frontend controls."""
from rest_framework.permissions import BasePermission
from apps.observability.permissions import allowed


class ObservabilityPermission(BasePermission):
    codename = None

    def has_permission(self, request, view):
        return bool(self.codename and allowed(request.user, self.codename))


class ViewIncidents(ObservabilityPermission):
    codename = "view_observability_incidents"


class CreateIncidents(ObservabilityPermission):
    codename = "create_observability_incidents"


class AssignIncidents(ObservabilityPermission):
    codename = "assign_observability_incidents"


class ManageIncidents(ObservabilityPermission):
    codename = "manage_observability_incidents"


class RequestAIDiagnosis(ObservabilityPermission):
    codename = "request_observability_ai_diagnosis"


class ViewOperations(ObservabilityPermission):
    codename = "view_observability_operations"


class RequestOperations(ObservabilityPermission):
    codename = "request_observability_operations"


class ApproveOperations(ObservabilityPermission):
    codename = "approve_observability_operations"


class ViewAuditLogs(ObservabilityPermission):
    codename = "view_observability_audit_logs"


class SensitiveLogFieldsMixin:
    """Hide identity/traceback/metadata fields unless specifically authorized."""

    def get_serializer_class(self):
        from apps.observability.workflow_serializers import (
            ErrorSummarySerializer, RequestSummarySerializer, CeleryTaskSummarySerializer,
        )
        from apps.observability.permissions import allowed
        if allowed(self.request.user, "view_observability_error_details"):
            return super().get_serializer_class()
        safe = {
            "RequestLogViewSet": RequestSummarySerializer,
            "ErrorLogViewSet": ErrorSummarySerializer,
            "CeleryTaskLogViewSet": CeleryTaskSummarySerializer,
        }
        return safe.get(self.__class__.__name__, super().get_serializer_class())
