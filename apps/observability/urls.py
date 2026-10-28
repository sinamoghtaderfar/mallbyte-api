from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.observability.workflow_views import IncidentViewSet, InfrastructureOperationViewSet

from apps.observability.views import (
    AuditLogViewSet,
    CeleryTaskLogViewSet,
    ErrorLogViewSet,
    ObservabilityAlertViewSet,
    ObservabilityHealthView,
    ObservabilityStatsView,
    RequestLogViewSet,
    SystemHealthSnapshotViewSet,
)

router = DefaultRouter()
router.register(
    "request-logs",
    RequestLogViewSet,
    basename="observability-request-log",
)
router.register(
    "error-logs",
    ErrorLogViewSet,
    basename="observability-error-log",
)
router.register(
    "audit-logs",
    AuditLogViewSet,
    basename="observability-audit-log",
)
router.register(
    "system-health-snapshots",
    SystemHealthSnapshotViewSet,
    basename="observability-system-health-snapshot",
)
router.register(
    "alerts",
    ObservabilityAlertViewSet,
    basename="observability-alert",
)
router.register(
    "celery-task-logs",
    CeleryTaskLogViewSet,
    basename="observability-celery-task-log",
)

router.register("incidents", IncidentViewSet, basename="observability-incident")
router.register("operations", InfrastructureOperationViewSet, basename="observability-operation")

urlpatterns = [
    path("health/", ObservabilityHealthView.as_view(), name="observability-health"),
    path("stats/", ObservabilityStatsView.as_view(), name="observability-stats"),
]

urlpatterns += router.urls