import csv

from django.http import StreamingHttpResponse
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.permissions import (
    CanExportAnalytics,
    CanViewPlatformAnalytics,
)
from apps.settlements.reconciliation import (
    reconciliation_report,
    seller_balance_rows,
)


class ReportQuerySerializer(serializers.Serializer):
    sample_limit = serializers.IntegerField(
        required=False,
        default=20,
        min_value=1,
        max_value=100,
    )


class BalanceQuerySerializer(serializers.Serializer):
    seller_id = serializers.IntegerField(
        required=False,
        min_value=1,
    )
    currency = serializers.RegexField(
        regex=r"^[A-Za-z]{3,10}$",
        required=False,
        max_length=10,
    )
    page = serializers.IntegerField(
        required=False,
        default=1,
        min_value=1,
    )
    page_size = serializers.IntegerField(
        required=False,
        default=20,
        min_value=1,
        max_value=100,
    )


class ReconciliationView(APIView):
    permission_classes = [
        IsAuthenticated,
        CanViewPlatformAnalytics,
    ]

    def get(self, request):
        query = ReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        result = reconciliation_report(
            sample_limit=query.validated_data["sample_limit"]
        )

        return Response(result)


class BalanceView(APIView):
    permission_classes = [
        IsAuthenticated,
        CanViewPlatformAnalytics,
    ]

    def get(self, request):
        query = BalanceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        values = query.validated_data

        rows = seller_balance_rows(
            seller_id=values.get("seller_id"),
            currency=values.get("currency"),
        )

        page = values["page"]
        size = values["page_size"]
        start = (page - 1) * size

        results = [
            {
                "seller_id": row["seller_id"],
                "currency": row["currency"],
                "balance": str(row["balance"]),
                "entry_count": row["entry_count"],
            }
            for row in rows[start : start + size]
        ]

        return Response(
            {
                "scope": "platform",
                "count": rows.count(),
                "page": page,
                "page_size": size,
                "results": results,
            }
        )


class CsvStreamBuffer:
    def write(self, value):
        return value


def _csv_safe(value):
    text = str(value if value is not None else "")

    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + text

    return text


class ReconciliationExportView(APIView):
    permission_classes = [
        IsAuthenticated,
        CanViewPlatformAnalytics,
        CanExportAnalytics,
    ]

    def get(self, request):
        query = ReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        result = reconciliation_report(
            sample_limit=query.validated_data["sample_limit"]
        )

        writer = csv.writer(CsvStreamBuffer())

        def stream():
            yield "\ufeff" + writer.writerow(
                [
                    "check",
                    "count",
                    "sample_ids",
                    "generated_at",
                ]
            )

            for name, finding in result["findings"].items():
                ids = finding.get(
                    "sample_ids",
                    finding.get(
                        "sample_allocation_ids",
                        [],
                    ),
                )

                yield writer.writerow(
                    [
                        name,
                        finding["count"],
                        ";".join(str(i) for i in ids),
                        result["generated_at"],
                    ]
                )

        response = StreamingHttpResponse(
            stream(),
            content_type="text/csv; charset=utf-8",
        )

        response["Content-Disposition"] = (
            "attachment; filename=" '"settlement_reconciliation_summary.csv"'
        )
        response["Cache-Control"] = "no-store"

        return response


class BalanceExportView(APIView):
    permission_classes = [
        IsAuthenticated,
        CanViewPlatformAnalytics,
        CanExportAnalytics,
    ]

    def get(self, request):
        query = BalanceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        values = query.validated_data

        rows = seller_balance_rows(
            seller_id=values.get("seller_id"),
            currency=values.get("currency"),
        )

        writer = csv.writer(CsvStreamBuffer())

        def stream():
            yield "\ufeff" + writer.writerow(
                [
                    "seller_id",
                    "currency",
                    "balance",
                    "entry_count",
                ]
            )

            for row in rows.iterator(chunk_size=1000):
                yield writer.writerow(
                    [
                        _csv_safe(row["seller_id"]),
                        _csv_safe(row["currency"]),
                        _csv_safe(str(row["balance"])),
                        row["entry_count"],
                    ]
                )

        response = StreamingHttpResponse(
            stream(),
            content_type="text/csv; charset=utf-8",
        )

        response["Content-Disposition"] = (
            "attachment; filename=" '"seller_ledger_balances.csv"'
        )
        response["Cache-Control"] = "no-store"

        return response
