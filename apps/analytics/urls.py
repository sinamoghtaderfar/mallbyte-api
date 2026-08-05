from django.urls import path

from apps.analytics.views import (
    AnalyticsBreakdownView,
    AnalyticsTimeSeriesView,
    DashboardAnalyticsView,
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
]