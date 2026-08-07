import csv

from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.models import (
    AnalyticsGeneratedReport,
    AnalyticsReportSchedule,
)
from apps.analytics.permissions import IsAnalyticsAdmin
from apps.analytics.serializers import (
    AnalyticsAlertsQuerySerializer,
    AnalyticsBreakdownQuerySerializer,
    AnalyticsExportQuerySerializer,
    AnalyticsGeneratedReportSerializer,
    AnalyticsReportScheduleSerializer,
    DashboardQuerySerializer,
    GenerateAnalyticsReportNowSerializer,
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
from apps.analytics.tasks import (
    create_reports_for_schedule,
    generate_analytics_report,
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
    



class AnalyticsReportScheduleViewSet(viewsets.ModelViewSet):
    serializer_class = AnalyticsReportScheduleSerializer
    permission_classes = [IsAuthenticated, IsAnalyticsAdmin]

    def get_queryset(self):
        return AnalyticsReportSchedule.objects.select_related(
            "created_by"
        ).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        instance = serializer.save()
        instance.next_run_at = instance.calculate_next_run()
        instance.save(
            update_fields=[
                "next_run_at",
                "updated_at",
            ]
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="run-now",
    )
    def run_now(self, request, pk=None):
        schedule = self.get_object()

        reports = create_reports_for_schedule(
            schedule=schedule,
            generated_by=request.user,
        )

        for report in reports:
            generate_analytics_report.delay(str(report.id))

        serializer = AnalyticsGeneratedReportSerializer(
            reports,
            many=True,
            context={"request": request},
        )

        return Response(
            {
                "detail": "Reports have been queued successfully.",
                "queued_reports": serializer.data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AnalyticsGeneratedReportViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AnalyticsGeneratedReportSerializer
    permission_classes = [IsAuthenticated, IsAnalyticsAdmin]

    def get_queryset(self):
        queryset = AnalyticsGeneratedReport.objects.select_related(
            "schedule",
            "generated_by",
        ).order_by("-created_at")

        status_value = self.request.query_params.get("status")
        report_type = self.request.query_params.get("report_type")
        period = self.request.query_params.get("period")
        schedule_id = self.request.query_params.get("schedule")

        if status_value:
            queryset = queryset.filter(status=status_value)

        if report_type:
            queryset = queryset.filter(report_type=report_type)

        if period:
            queryset = queryset.filter(period=period)

        if schedule_id:
            queryset = queryset.filter(schedule_id=schedule_id)

        return queryset

    @action(
        detail=True,
        methods=["get"],
        url_path="download",
    )
    def download(self, request, pk=None):
        report = get_object_or_404(
            AnalyticsGeneratedReport,
            pk=pk,
            status=AnalyticsGeneratedReport.StatusChoices.SUCCESS,
        )

        if not report.file:
            return Response(
                {
                    "detail": "Report file is not available."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        filename = report.filename or report.file.name.split("/")[-1]

        response = FileResponse(
            report.file.open("rb"),
            as_attachment=True,
            filename=filename,
        )

        return response


class GenerateAnalyticsReportNowView(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsAnalyticsAdmin]

    def create(self, request):
        serializer = GenerateAnalyticsReportNowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        report_types = serializer.validated_data["report_types"]
        period = serializer.validated_data["period"]

        reports = []

        for report_type in report_types:
            report = AnalyticsGeneratedReport.objects.create(
                report_type=report_type,
                period=period,
                generated_by=request.user,
            )
            generate_analytics_report.delay(str(report.id))
            reports.append(report)

        output_serializer = AnalyticsGeneratedReportSerializer(
            reports,
            many=True,
            context={"request": request},
        )

        return Response(
            {
                "detail": "Reports have been queued successfully.",
                "queued_reports": output_serializer.data,
            },
            status=status.HTTP_202_ACCEPTED,
        )