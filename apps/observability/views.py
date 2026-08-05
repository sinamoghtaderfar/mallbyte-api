from datetime import timedelta

from django.db.models import Avg, Count
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.observability.models import (
    AuditLog,
    CeleryTaskLog,
    ErrorLog,
    ObservabilityAlert,
    RequestLog,
    SystemHealthSnapshot,
)
from apps.observability.permissions import IsObservabilityAdmin
from apps.observability.serializers import (
    AuditLogSerializer,
    CeleryTaskLogSerializer,
    ErrorLogSerializer,
    ObservabilityAlertSerializer,
    RequestLogSerializer,
    SystemHealthSnapshotSerializer,
)
from apps.observability.services import collect_system_health_snapshot


class ObservabilityHealthView(APIView):
    permission_classes = [IsAuthenticated, IsObservabilityAdmin]

    def get(self, request):
        snapshot = collect_system_health_snapshot()

        serializer = SystemHealthSnapshotSerializer(snapshot)

        return Response(serializer.data)


class ObservabilityStatsView(APIView):
    permission_classes = [IsAuthenticated, IsObservabilityAdmin]

    def get(self, request):
        now = timezone.now()
        last_24_hours = now - timedelta(hours=24)

        request_logs = RequestLog.objects.filter(
            created_at__gte=last_24_hours,
        )

        error_logs = ErrorLog.objects.filter(
            created_at__gte=last_24_hours,
        )

        open_alerts = ObservabilityAlert.objects.filter(
            status=ObservabilityAlert.StatusChoices.OPEN,
        )

        return Response(
            {
                "window": "last_24_hours",
                "requests_count": request_logs.count(),
                "error_logs_count": error_logs.count(),
                "open_alerts_count": open_alerts.count(),
                "slow_requests_count": request_logs.filter(
                    duration_ms__gte=1000,
                ).count(),
                "average_duration_ms": request_logs.aggregate(
                    average=Avg("duration_ms"),
                )["average"] or 0,
                "status_codes": list(
                    request_logs.values("status_code")
                    .annotate(count=Count("id"))
                    .order_by("status_code")
                ),
                "top_paths": list(
                    request_logs.values("path")
                    .annotate(count=Count("id"))
                    .order_by("-count")[:10]
                ),
                "open_alerts_by_severity": list(
                    open_alerts.values("severity")
                    .annotate(count=Count("id"))
                    .order_by("severity")
                ),
            }
        )


class RequestLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RequestLogSerializer
    permission_classes = [IsAuthenticated, IsObservabilityAdmin]

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


class ErrorLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ErrorLogSerializer
    permission_classes = [IsAuthenticated, IsObservabilityAdmin]

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
    )
    def resolve(self, request, pk=None):
        error_log = self.get_object()
        error_log.mark_resolved(user=request.user)

        serializer = self.get_serializer(error_log)

        return Response(serializer.data)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, IsObservabilityAdmin]

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
    )
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        alert.acknowledge(user=request.user)

        serializer = self.get_serializer(alert)

        return Response(serializer.data)

    @action(
        detail=True,
        methods=["post"],
        url_path="resolve",
    )
    def resolve(self, request, pk=None):
        alert = self.get_object()
        alert.resolve(user=request.user)

        serializer = self.get_serializer(alert)

        return Response(serializer.data)


class CeleryTaskLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CeleryTaskLogSerializer
    permission_classes = [IsAuthenticated, IsObservabilityAdmin]

    def get_queryset(self):
        queryset = CeleryTaskLog.objects.order_by("-created_at")

        status_value = self.request.query_params.get("status")
        task_name = self.request.query_params.get("task_name")

        if status_value:
            queryset = queryset.filter(status=status_value)

        if task_name:
            queryset = queryset.filter(task_name__icontains=task_name)

        return queryset