from django.urls import path

from apps.analytics.views import DashboardAnalyticsView


urlpatterns = [
    path(
        "dashboard/",
        DashboardAnalyticsView.as_view(),
        name="analytics-dashboard",
    ),
]