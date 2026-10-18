from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.permissions import CanViewSellerAnalytics
from apps.analytics.seller_services import get_seller_analytics


class SellerAnalyticsQuerySerializer(serializers.Serializer):
    period = serializers.ChoiceField(
        choices=["today", "week", "month", "year", "all"],
        default="month",
        required=False,
    )
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    limit = serializers.IntegerField(
        min_value=1, max_value=50, default=10, required=False
    )

    def validate(self, attrs):
        start, end = attrs.get("start_date"), attrs.get("end_date")
        if (start is None) != (end is None):
            raise serializers.ValidationError(
                "Both start_date and end_date are required."
            )
        if start is not None and start > end:
            raise serializers.ValidationError("start_date cannot exceed end_date.")
        return attrs


class SellerAnalyticsBaseView(APIView):
    permission_classes = [IsAuthenticated, CanViewSellerAnalytics]
    dimension = "dashboard"

    def get(self, request):
        serializer = SellerAnalyticsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        if self.dimension == "timeseries":
            start, end = params.get("start_date"), params.get("end_date")
            if start is None and params.get("period", "month") == "all":
                raise serializers.ValidationError(
                    {"period": "Use a bounded period for time series."}
                )
            if start is not None and (end - start).days > 365:
                raise serializers.ValidationError(
                    {"date_range": "Maximum 366 calendar days."}
                )
        return Response(
            get_seller_analytics(
                seller_id=request.user.pk,
                period=params.get("period", "month"),
                start_date=params.get("start_date"),
                end_date=params.get("end_date"),
                dimension=self.dimension,
                limit=params.get("limit", 10),
            )
        )


class SellerDashboardView(SellerAnalyticsBaseView):
    dimension = "dashboard"


class SellerTimeSeriesView(SellerAnalyticsBaseView):
    dimension = "timeseries"


class SellerProductsView(SellerAnalyticsBaseView):
    dimension = "products"
