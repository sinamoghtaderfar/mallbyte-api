"""DEVELOPMENT ONLY: a deliberately simulated payment/return/payout provider.

No HTTP request to a bank or payment provider is made. Every simulated
confirmation is unambiguously prefixed DEMO and uses existing idempotent
ledger posting services. These endpoints must never be enabled in production.
"""
import hashlib
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Seller
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.settlements.services import post_confirmed_payout, post_verified_refund


class DemoAdminOnly(BasePermission):
    message = "Demo financial operations are restricted to local development superusers."

    def has_permission(self, request, view):
        u = request.user
        return bool(
            settings.DEBUG
            and getattr(settings, "SETTLEMENTS_DEMO_ENABLED", False)
            and getattr(settings, "SETTLEMENTS_LEDGER_ENABLED", False)
            and u.is_authenticated and u.is_active and u.is_superuser
            and not getattr(u, "is_deleted", False)
        )


class CaptureInput(serializers.Serializer):
    payment_id = serializers.IntegerField(min_value=1)


class FailedInput(CaptureInput):
    reason = serializers.CharField(max_length=255, default="Simulated gateway rejection")


class RefundLine(serializers.Serializer):
    order_item_id = serializers.IntegerField(min_value=1)
    merchandise = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0"))
    shipping = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0"))
    tax = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0"))


class RefundInput(serializers.Serializer):
    payment_id = serializers.IntegerField(min_value=1)
    return_request_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    currency = serializers.RegexField(regex=r"^[A-Za-z]{3,10}$")
    idempotency_key = serializers.CharField(max_length=100, min_length=8)
    lines = RefundLine(many=True, allow_empty=False)


class PayoutInput(serializers.Serializer):
    seller_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    currency = serializers.RegexField(regex=r"^[A-Za-z]{3,10}$")
    idempotency_key = serializers.CharField(max_length=100, min_length=8)


def demo_reference(kind, key):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]
    return f"DEMO-{kind}-{digest}"


class DemoBaseView(APIView):
    permission_classes = [IsAuthenticated, DemoAdminOnly]
    http_method_names = ["post", "options"]
    serializer_class = None

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = self.perform_demo(serializer.validated_data)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_409_CONFLICT)
        except (ObjectDoesNotExist, IntegrityError):
            return Response({"detail": "Demo event cannot be reconciled."}, status=status.HTTP_409_CONFLICT)
        return Response({"simulation": True, **result})


class DemoCaptureView(DemoBaseView):
    serializer_class = CaptureInput

    @transaction.atomic
    def perform_demo(self, data):
        order_id = Payment.objects.values_list("order_id", flat=True).get(pk=data["payment_id"])
        Order.objects.select_for_update().get(pk=order_id)
        payment = Payment.objects.select_for_update().get(pk=data["payment_id"])
        if payment.provider != Payment.ProviderChoices.MOCK:
            raise DjangoValidationError("Demo only accepts mock payments.")
        reference = demo_reference("CAPTURE", str(payment.pk))
        if payment.status in (Payment.StatusChoices.SUCCESS, Payment.StatusChoices.REFUNDED):
            if payment.gateway_reference != reference:
                raise DjangoValidationError("Capture belongs to a different source.")
            return {"payment_id": payment.pk, "status": payment.status, "replayed": True}
        if payment.status != Payment.StatusChoices.PENDING:
            raise DjangoValidationError("Only pending mock payments can be captured.")
        payment.mark_success(gateway_reference=reference, gateway_response={"simulated": True})
        return {"payment_id": payment.pk, "status": Payment.StatusChoices.SUCCESS, "replayed": False}


class DemoFailView(DemoBaseView):
    serializer_class = FailedInput

    @transaction.atomic
    def perform_demo(self, data):
        order_id = Payment.objects.values_list("order_id", flat=True).get(pk=data["payment_id"])
        Order.objects.select_for_update().get(pk=order_id)
        payment = Payment.objects.select_for_update().get(pk=data["payment_id"])
        if payment.provider != Payment.ProviderChoices.MOCK:
            raise DjangoValidationError("Demo only accepts mock payments.")
        if payment.status == Payment.StatusChoices.FAILED and payment.failure_reason == data["reason"]:
            return {"payment_id": payment.pk, "status": payment.status, "replayed": True}
        if payment.status != Payment.StatusChoices.PENDING:
            raise DjangoValidationError("Only pending mock payments can be failed.")
        payment.mark_failed(reason=data["reason"], gateway_response={"simulated": True})
        return {"payment_id": payment.pk, "status": Payment.StatusChoices.FAILED, "replayed": False}


class DemoRefundView(DemoBaseView):
    serializer_class = RefundInput

    def perform_demo(self, data):
        payment = Payment.objects.only("provider").get(pk=data["payment_id"])
        if payment.provider != Payment.ProviderChoices.MOCK:
            raise DjangoValidationError("Demo only accepts mock payments.")
        refund = post_verified_refund(
            payment_id=data["payment_id"],
            return_request_id=data["return_request_id"],
            confirmed_amount=data["amount"], currency=data["currency"],
            gateway_reference=demo_reference("REFUND", data["idempotency_key"]),
            idempotency_key=f"demo-refund:{data['idempotency_key']}",
            confirmed_at=timezone.now(),
            lines=[dict(line) for line in data["lines"]],
        )
        return {"refund_id": refund.pk, "status": "simulated_confirmed"}


class DemoPayoutView(DemoBaseView):
    serializer_class = PayoutInput

    def perform_demo(self, data):
        if not Seller.objects.filter(
            user_id=data["seller_id"], status=Seller.StatusChoices.APPROVED
        ).exists():
            raise DjangoValidationError("Seller is not approved.")
        payout = post_confirmed_payout(
            seller_id=data["seller_id"], currency=data["currency"],
            amount=data["amount"],
            external_reference=demo_reference("PAYOUT", data["idempotency_key"]),
            idempotency_key=f"demo-payout:{data['idempotency_key']}",
            confirmed_at=timezone.now(),
        )
        return {"payout_id": payout.pk, "status": "simulated_confirmed"}
