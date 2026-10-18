from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers

from apps.analytics.permissions import CanViewSellerAnalytics, CanViewPlatformAnalytics
from apps.settlements.readiness import financial_readiness
from apps.settlements.settlement_policy import payout_eligibility


class PayoutEligibilityQuerySerializer(serializers.Serializer):
    currency = serializers.CharField(max_length=10)


class SellerPayoutEligibilityView(APIView):
    permission_classes = [IsAuthenticated, CanViewSellerAnalytics]

    def get(self, request):
        serializer = PayoutEligibilityQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        # Scope ALWAYS comes from the authenticated user, never query input.
        return Response(payout_eligibility(request.user.pk, serializer.validated_data["currency"]))


class SettlementReadinessView(APIView):
    permission_classes = [IsAuthenticated, CanViewPlatformAnalytics]

    def get(self, request):
        return Response(financial_readiness())
