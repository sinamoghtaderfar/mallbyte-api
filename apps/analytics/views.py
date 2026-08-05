import csv

from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.permissions import IsAnalyticsAdmin
from apps.analytics.serializers import (
    AnalyticsAlertsQuerySerializer,
    AnalyticsBreakdownQuerySerializer,
    AnalyticsExportQuerySerializer,
    DashboardQuerySerializer,
    TimeSeriesQuerySerializer,
)
from apps.analytics.services import (
    build_csv_export_data,
    get_analytics_alerts,
    get_analytics_breakdown,
    get_analytics_timeseries,
    get_dashboard_analytics,
    safe_csv_value,
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

class AnalyticsExportView(APIView):
    permission_classes = [
        IsAuthenticated,
        IsAnalyticsAdmin,
    ]

    def get(self, request):
        serializer = AnalyticsExportQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        export_data = build_csv_export_data(
            report=serializer.validated_data.get("report", "sales"),
            period=serializer.validated_data.get("period", "month"),
            start_date=serializer.validated_data.get("start_date"),
            end_date=serializer.validated_data.get("end_date"),
        )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="{export_data["filename"]}"'
        )

        writer = csv.writer(response)

        writer.writerow(export_data["headers"])

        for row in export_data["rows"]:
            writer.writerow([safe_csv_value(value) for value in row])

        return response