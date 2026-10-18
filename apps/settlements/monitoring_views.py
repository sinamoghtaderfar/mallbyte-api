"""Platform-scoped read-only audit history and privileged manual audits."""
from uuid import uuid4

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.permissions import CanManageAnalyticsReports, CanViewPlatformAnalytics
from apps.settlements.monitoring import record_financial_audit
from apps.settlements.monitoring_models import FinancialAuditAlert, FinancialAuditRun


class PageQuery(serializers.Serializer):
    page = serializers.IntegerField(default=1, min_value=1)
    page_size = serializers.IntegerField(default=20, min_value=1, max_value=100)


class RunInput(serializers.Serializer):
    sample_limit = serializers.IntegerField(default=20, min_value=1, max_value=100)


def run_summary(run):
    return {
        "id": run.pk, "run_key": run.run_key, "source": run.source,
        "status": run.status, "findings_count": run.findings_count,
        "created_at": run.created_at, "finished_at": run.finished_at,
    }


class FinancialAuditRunsView(APIView):
    permission_classes = [IsAuthenticated, CanViewPlatformAnalytics]

    def get(self, request):
        q = PageQuery(data=request.query_params)
        q.is_valid(raise_exception=True)
        page, size = q.validated_data["page"], q.validated_data["page_size"]
        qs = FinancialAuditRun.objects.all()
        return Response({
            "count": qs.count(), "page": page, "page_size": size,
            "results": [run_summary(r) for r in qs[(page - 1) * size:page * size]],
        })


class FinancialAuditRunDetailView(APIView):
    permission_classes = [IsAuthenticated, CanViewPlatformAnalytics]

    def get(self, request, pk):
        run = get_object_or_404(FinancialAuditRun, pk=pk)
        return Response({**run_summary(run), "summary": run.summary, "error": run.error})


class FinancialAuditAlertsView(APIView):
    permission_classes = [IsAuthenticated, CanViewPlatformAnalytics]

    def get(self, request):
        q = PageQuery(data=request.query_params)
        q.is_valid(raise_exception=True)
        qs = FinancialAuditAlert.objects.filter(is_open=True)
        page, size = q.validated_data["page"], q.validated_data["page_size"]
        return Response({
            "count": qs.count(), "page": page, "page_size": size,
            "results": [
                {"code": a.code, "findings_count": a.findings_count,
                 "sample": a.sample, "first_seen_at": a.first_seen_at,
                 "last_seen_at": a.last_seen_at, "last_run_id": a.last_run_id}
                for a in qs[(page - 1) * size:page * size]
            ],
        })


class FinancialAuditRunNowView(APIView):
    permission_classes = [IsAuthenticated, CanManageAnalyticsReports]
    http_method_names = ["post", "options"]

    def post(self, request):
        q = RunInput(data=request.data)
        q.is_valid(raise_exception=True)
        run, _ = record_financial_audit(
            run_key=f"manual:{uuid4().hex}", source="manual",
            sample_limit=q.validated_data["sample_limit"],
        )
        return Response(run_summary(run), status=status.HTTP_201_CREATED)
