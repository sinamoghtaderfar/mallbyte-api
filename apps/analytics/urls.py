from django.urls import path
from rest_framework.routers import DefaultRouter
from apps.analytics.views import (
    AnalyticsAlertsView,
    AnalyticsBreakdownView,
    AnalyticsExportView,
    AnalyticsTimeSeriesView,
    DashboardAnalyticsView,
)
from apps.analytics.views import (
    AnalyticsGeneratedReportViewSet,
    AnalyticsReportScheduleViewSet,
    GenerateAnalyticsReportNowView,
)

urlpatterns = [
    path(
        "dashboard/",
        DashboardAnalyticsView.as_view(),
        name="analytics-dashboard",
    ),
    path(
        "timeseries/",
        AnalyticsTimeSeriesView.as_view(),
        name="analytics-timeseries",
    ),
    path(
        "breakdown/",
        AnalyticsBreakdownView.as_view(),
        name="analytics-breakdown",
    ),
        path(
        "alerts/",
        AnalyticsAlertsView.as_view(),
        name="analytics-alerts",
    ),
        path(
        "export/",
        AnalyticsExportView.as_view(),
        name="analytics-export",
    ),
]

router = DefaultRouter()
router.register(
    "report-schedules",
    AnalyticsReportScheduleViewSet,
    basename="analytics-report-schedule",
)
router.register(
    "generated-reports",
    AnalyticsGeneratedReportViewSet,
    basename="analytics-generated-report",
)
router.register(
    "generate-report-now",
    GenerateAnalyticsReportNowView,
    basename="analytics-generate-report-now",
)

urlpatterns += router.urls