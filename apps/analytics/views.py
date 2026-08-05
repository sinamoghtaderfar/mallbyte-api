from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.permissions import IsAnalyticsAdmin
from apps.analytics.serializers import (
    AnalyticsAlertsQuerySerializer,
    AnalyticsBreakdownQuerySerializer,
    DashboardQuerySerializer,
    TimeSeriesQuerySerializer,
)
from apps.analytics.services import (
    get_analytics_alerts,
    get_analytics_breakdown,
    get_analytics_timeseries,
    get_dashboard_analytics,
)


class DashboardAnalyticsView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsAnalyticsAdmin,
    ]

    def get(self, request):
        serializer = DashboardQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        data = get_dashboard_analytics(
            period=serializer.validated_data.get("period", "month"),
            start_date=serializer.validated_data.get("start_date"),
            end_date=serializer.validated_data.get("end_date"),
        )

        return Response(data)


class AnalyticsTimeSeriesView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsAnalyticsAdmin,
    ]

    def get(self, request):
        serializer = TimeSeriesQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        data = get_analytics_timeseries(
            period=serializer.validated_data.get("period", "month"),
            start_date=serializer.validated_data.get("start_date"),
            end_date=serializer.validated_data.get("end_date"),
        )

        return Response(data)
    
class AnalyticsBreakdownView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsAnalyticsAdmin,
    ]

    def get(self, request):
        serializer = AnalyticsBreakdownQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        data = get_analytics_breakdown(
            period=serializer.validated_data.get("period", "month"),
            start_date=serializer.validated_data.get("start_date"),
            end_date=serializer.validated_data.get("end_date"),
            limit=serializer.validated_data.get("limit", 10),
        )

        return Response(data)
class AnalyticsAlertsView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsAnalyticsAdmin,
    ]

    def get(self, request):
        serializer = AnalyticsAlertsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        data = get_analytics_alerts(
            limit=serializer.validated_data.get("limit", 10),
        )

        return Response(data)