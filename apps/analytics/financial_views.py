from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.financial import get_financial_cashflow
from apps.analytics.permissions import CanViewPlatformAnalytics


class FinancialAnalyticsQuerySerializer(serializers.Serializer):
    PERIOD_CHOICES = [
        ("today", "Today"),
        ("week", "Last 7 calendar days"),
        ("month", "Last 30 calendar days"),
        ("year", "Last 365 calendar days"),
        ("all", "All time"),
    ]

    period = serializers.ChoiceField(
        choices=PERIOD_CHOICES,
        required=False,
        default="month",
    )

    start_date = serializers.DateField(
        required=False,
    )

    end_date = serializers.DateField(
        required=False,
    )

    def validate(self, attrs):
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")

        if (start_date is None) != (end_date is None):
            raise serializers.ValidationError(
                {"date_range": ("Both start_date and end_date " "are required.")}
            )

        if start_date is not None and end_date is not None and start_date > end_date:
            raise serializers.ValidationError(
                {"date_range": ("start_date cannot be after end_date.")}
            )

        return attrs


class FinancialAnalyticsView(APIView):
    permission_classes = [
        IsAuthenticated,
        CanViewPlatformAnalytics,
    ]

    def get(self, request):
        serializer = FinancialAnalyticsQuerySerializer(
            data=request.query_params,
        )
        serializer.is_valid(raise_exception=True)

        data = get_financial_cashflow(
            period=serializer.validated_data.get(
                "period",
                "month",
            ),
            start_date=serializer.validated_data.get(
                "start_date",
            ),
            end_date=serializer.validated_data.get(
                "end_date",
            ),
        )

        return Response(data)
