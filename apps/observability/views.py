from datetime import timedelta

from django.db.models import Avg, Count
from django.utils import timezone
from django.conf import settings
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from apps.observability.models import (
    AuditLog,
    CeleryTaskLog,
    ErrorLog,
    ObservabilityAlert,
    RequestLog,
    SystemHealthSnapshot,
)
from apps.observability.workflow_permissions import (
    SensitiveLogFieldsMixin, ViewAuditLogs,
)
from apps.observability.permissions import (
    IsObservabilityAdmin, IsObservabilityLogsReader,
    IsObservabilityAlertManager, IsObservabilityErrorManager,
)
from apps.observability.metrics import build_metrics
from apps.observability.serializers import (
    AuditLogSerializer,
    CeleryTaskLogSerializer,
    ErrorLogSerializer,
    ObservabilityAlertSerializer,
    RequestLogSerializer,
    SystemHealthSnapshotSerializer,
)
from apps.observability.services import create_audit_log


class ObservabilityHealthView(APIView):
    permission_classes = [IsAuthenticated, IsObservabilityAdmin]

    def get(self, request):
        # Read-only: periodic Celery Beat collection must own snapshot writes.
        snapshot = SystemHealthSnapshot.objects.order_by("-created_at").first()
        if snapshot is None:
            return Response({"status": "unknown", "detail": "No health snapshot yet. Run the scheduled collector."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        data = SystemHealthSnapshotSerializer(snapshot).data
        threshold = getattr(settings, "OBSERVABILITY_SNAPSHOT_STALE_SECONDS", 900)
        data["is_stale"] = (timezone.now() - snapshot.created_at).total_seconds() > threshold
        data["stale_after_seconds"] = threshold
        return Response(data)


class ObservabilityStatsView(APIView):
    permission_classes = [IsAuthenticated, IsObservabilityAdmin]

    def get(self, request):
        return Response(build_metrics(request.query_params.get("window", "24h")))


class RequestLogViewSet(SensitiveLogFieldsMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = RequestLogSerializer
    permission_classes = [IsAuthenticated, IsObservabilityLogsReader]

    def get_queryset(self):
        queryset = RequestLog.objects.select_related("user").order_by(
            "-created_at"
        )

        status_code = self.request.query_params.get("status_code")
        method = self.request.query_params.get("method")
        path = self.request.query_params.get("path")
        slow = self.request.query_params.get("slow")
        error = self.request.query_params.get("error")

        if status_code:
            queryset = queryset.filter(status_code=status_code)

        if method:
            queryset = queryset.filter(method=method.upper())

        if path:
            queryset = queryset.filter(path__icontains=path)

        if slow == "true":
            queryset = queryset.filter(duration_ms__gte=1000)

        if error == "true":
            queryset = queryset.filter(status_code__gte=500)

        return queryset


class ErrorLogViewSet(SensitiveLogFieldsMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ErrorLogSerializer
    permission_classes = [IsAuthenticated, IsObservabilityLogsReader]

    def get_queryset(self):
        queryset = ErrorLog.objects.select_related(
            "user",
            "resolved_by",
            "request_log",
        ).order_by("-created_at")

        is_resolved = self.request.query_params.get("is_resolved")
        severity = self.request.query_params.get("severity")
        exception_type = self.request.query_params.get("exception_type")
        path = self.request.query_params.get("path")

        if is_resolved in ["true", "false"]:
            queryset = queryset.filter(is_resolved=is_resolved == "true")

        if severity:
            queryset = queryset.filter(severity=severity)

        if exception_type:
            queryset = queryset.filter(exception_type__icontains=exception_type)

        if path:
            queryset = queryset.filter(path__icontains=path)

        return queryset

    @action(
        detail=True,
        methods=["post"],
        url_path="resolve",
        permission_classes=[IsAuthenticated, IsObservabilityErrorManager],
    )
    def resolve(self, request, pk=None):
        error_log = self.get_object()
        error_log.mark_resolved(user=request.user)
        create_audit_log(actor=request.user, action=AuditLog.ActionChoices.UPDATE,
                         description="Resolved observability error", object_type="ErrorLog",
                         object_id=str(error_log.id), request=request)

        serializer = self.get_serializer(error_log)

        return Response(serializer.data)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, ViewAuditLogs]

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("actor").order_by(
            "-created_at"
        )

        action = self.request.query_params.get("action")
        object_type = self.request.query_params.get("object_type")
        object_id = self.request.query_params.get("object_id")

        if action:
            queryset = queryset.filter(action=action)

        if object_type:
            queryset = queryset.filter(object_type__icontains=object_type)

        if object_id:
            queryset = queryset.filter(object_id=object_id)

        return queryset


class SystemHealthSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SystemHealthSnapshotSerializer
    permission_classes = [IsAuthenticated, IsObservabilityAdmin]

    def get_queryset(self):
        queryset = SystemHealthSnapshot.objects.order_by("-created_at")

        status_value = self.request.query_params.get("status")

        if status_value:
            queryset = queryset.filter(status=status_value)

        return queryset


class ObservabilityAlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ObservabilityAlertSerializer
    permission_classes = [IsAuthenticated, IsObservabilityAdmin]

    def get_queryset(self):
        queryset = ObservabilityAlert.objects.select_related(
            "acknowledged_by",
            "resolved_by",
        ).order_by("-created_at")

        status_value = self.request.query_params.get("status")
        severity = self.request.query_params.get("severity")
        alert_type = self.request.query_params.get("alert_type")
        source = self.request.query_params.get("source")

        if status_value:
            queryset = queryset.filter(status=status_value)

        if severity:
            queryset = queryset.filter(severity=severity)

        if alert_type:
            queryset = queryset.filter(alert_type=alert_type)

        if source:
            queryset = queryset.filter(source=source)

        return queryset

    @action(
        detail=True,
        methods=["post"],
        url_path="acknowledge",
        permission_classes=[IsAuthenticated, IsObservabilityAlertManager],
    )
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        if alert.status != ObservabilityAlert.StatusChoices.OPEN:
            return Response({"detail": "Only open alerts can be acknowledged."}, status=409)
        alert.acknowledge(user=request.user)
        create_audit_log(actor=request.user, action=AuditLog.ActionChoices.UPDATE,
                         description="Acknowledged observability alert",
                         object_type="ObservabilityAlert", object_id=str(alert.id), request=request)

        serializer = self.get_serializer(alert)

        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="resolve",
        permission_classes=[IsAuthenticated, IsObservabilityAlertManager],
    )
    def resolve(self, request, pk=None):
        alert = self.get_object()
        if alert.status == ObservabilityAlert.StatusChoices.RESOLVED:
            return Response({"detail": "Alert is already resolved."}, status=409)
        alert.resolve(user=request.user)
        create_audit_log(actor=request.user, action=AuditLog.ActionChoices.UPDATE,
                         description="Resolved observability alert",
                         object_type="ObservabilityAlert", object_id=str(alert.id), request=request)

        serializer = self.get_serializer(alert)

        return Response(serializer.data)


class CeleryTaskLogViewSet(SensitiveLogFieldsMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = CeleryTaskLogSerializer
    permission_classes = [IsAuthenticated, IsObservabilityLogsReader]

    def get_queryset(self):
        queryset = CeleryTaskLog.objects.order_by("-created_at")

        status_value = self.request.query_params.get("status")
        task_name = self.request.query_params.get("task_name")

        if status_value:
            queryset = queryset.filter(status=status_value)

        if task_name:
            queryset = queryset.filter(task_name__icontains=task_name)

        return queryset