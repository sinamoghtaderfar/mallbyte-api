"""HMAC-authenticated internal settlement-confirmation bridge.

IMPORTANT: This is NOT a direct bank/payment-provider webhook validator.
Only an upstream adapter which has ALREADY independently verified the provider
signature, transaction identity, amount and final state may sign these events.
Never expose bridge secrets to browser/mobile clients or merchants.
"""
import hashlib
import hmac
import json
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import (
    ObjectDoesNotExist, ValidationError as DjangoValidationError,
)
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Seller
from apps.payments.models import Payment
from apps.settlements.services import post_confirmed_payout, post_verified_refund


MAX_BODY_BYTES = 64 * 1024
MAX_SKEW_SECONDS = 300


class InvalidBridgeSignature(Exception):
    pass


def verify_bridge_signature(request, *, secret_setting):
    secret = getattr(settings, secret_setting, "")
    if not isinstance(secret, str) or len(secret) < 32:
        raise InvalidBridgeSignature("Bridge not configured")
    raw = request.body
    if not raw or len(raw) > MAX_BODY_BYTES:
        raise InvalidBridgeSignature("Invalid payload")
    sent_at = request.headers.get("X-Settlement-Timestamp", "")
    signature = request.headers.get("X-Settlement-Signature", "")
    try:
        timestamp = int(sent_at)
    except (ValueError, TypeError):
        raise InvalidBridgeSignature("Invalid timestamp") from None
    if not sent_at.isascii() or not sent_at.isdigit():
        raise InvalidBridgeSignature("Invalid timestamp")
    if abs(int(timezone.now().timestamp()) - timestamp) > MAX_SKEW_SECONDS:
        raise InvalidBridgeSignature("Expired signature")
    expected = hmac.new(
        secret.encode("utf-8"),
        sent_at.encode("ascii") + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise InvalidBridgeSignature("Signature mismatch")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise InvalidBridgeSignature("Invalid JSON") from None
    if not isinstance(payload, dict):
        raise InvalidBridgeSignature("Invalid JSON object")
    return payload


class AmountLineSerializer(serializers.Serializer):
    order_item_id = serializers.IntegerField(min_value=1)
    merchandise = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    shipping = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    tax = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)


class RefundConfirmationSerializer(serializers.Serializer):
    event = serializers.ChoiceField(choices=["refund.confirmed"])
    payment_id = serializers.IntegerField(min_value=1)
    return_request_id = serializers.IntegerField(min_value=1)
    provider = serializers.ChoiceField(choices=Payment.ProviderChoices.choices)
    confirmed_amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    currency = serializers.CharField(max_length=10)
    gateway_reference = serializers.CharField(max_length=255, allow_blank=False)
    idempotency_key = serializers.CharField(max_length=160, allow_blank=False)
    confirmed_at = serializers.DateTimeField()
    lines = AmountLineSerializer(many=True, allow_empty=False)


class PayoutConfirmationSerializer(serializers.Serializer):
    event = serializers.ChoiceField(choices=["payout.confirmed"])
    seller_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    currency = serializers.CharField(max_length=10)
    external_reference = serializers.CharField(max_length=255, allow_blank=False)
    idempotency_key = serializers.CharField(max_length=160, allow_blank=False)
    confirmed_at = serializers.DateTimeField()


class CaptureConfirmationSerializer(serializers.Serializer):
    event = serializers.ChoiceField(choices=["payment.captured"])
    payment_id = serializers.IntegerField(min_value=1)
    provider = serializers.ChoiceField(choices=Payment.ProviderChoices.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    currency = serializers.CharField(max_length=10)
    gateway_reference = serializers.CharField(max_length=255, allow_blank=False)
    confirmed_at = serializers.DateTimeField()


class SignedBridgeView(APIView):
    # DRF authentication is disabled: only the complete verified HMAC payload
    # grants access, using separate per-purpose secrets.
    authentication_classes = []
    permission_classes = [AllowAny]
    http_method_names = ["post", "options"]
    secret_setting = ""
    serializer_class = serializers.Serializer

    def post(self, request):
        if not getattr(settings, "SETTLEMENTS_LEDGER_ENABLED", False):
            return Response({"detail": "Financial integration disabled"}, status=503)
        try:
            payload = verify_bridge_signature(request, secret_setting=self.secret_setting)
        except InvalidBridgeSignature:
            return Response({"detail": "Invalid signed event"}, status=403)
        serializer = self.serializer_class(data=payload)
        serializer.is_valid(raise_exception=True)
        try:
            event_id = self.handle_event(serializer.validated_data)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=409)
        except (ObjectDoesNotExist, IntegrityError):
            return Response({"detail": "Financial event cannot be reconciled"}, status=409)
        return Response({"accepted": True, "id": event_id}, status=status.HTTP_200_OK)


class CaptureConfirmationView(SignedBridgeView):
    secret_setting = "SETTLEMENTS_CAPTURE_BRIDGE_SECRET"
    serializer_class = CaptureConfirmationSerializer

    def handle_event(self, event):
        from django.db import transaction
        from apps.orders.models import Order
        from apps.settlements.services import money, post_captured_payment
        # Same lock sequence used by Payment.mark_success and post_captured_payment.
        with transaction.atomic():
            order_id = Payment.objects.values_list("order_id", flat=True).get(pk=event["payment_id"])
            Order.objects.select_for_update().get(pk=order_id)
            payment = Payment.objects.select_for_update().get(pk=event["payment_id"])
            if payment.provider != event["provider"]:
                raise DjangoValidationError("Payment provider mismatch")
            if payment.provider == Payment.ProviderChoices.MOCK and not getattr(settings, "SETTLEMENTS_ALLOW_SIGNED_MOCK_EVENTS", False):
                raise DjangoValidationError("Mock captures are disabled")
            if money(payment.amount) != money(event["amount"]) or payment.currency.upper() != event["currency"].upper():
                raise DjangoValidationError("Payment currency/amount mismatch")
            if payment.status in (Payment.StatusChoices.SUCCESS, Payment.StatusChoices.REFUNDED):
                if payment.gateway_reference != event["gateway_reference"]:
                    raise DjangoValidationError("Conflicting capture reference")
                post_captured_payment(payment)
                return str(payment.pk)
            if payment.status != Payment.StatusChoices.PENDING:
                raise DjangoValidationError("Payment cannot be captured from current state")
            if Payment.objects.filter(provider=payment.provider, gateway_reference=event["gateway_reference"], status__in=(Payment.StatusChoices.SUCCESS, Payment.StatusChoices.REFUNDED)).exclude(pk=payment.pk).exists():
                raise DjangoValidationError("Duplicate gateway capture reference")
            # mark_success performs stock mutation, order transition and ledger
            # posting in ONE DB transaction (when integration enabled).
            payment.mark_success(
                gateway_reference=event["gateway_reference"],
                gateway_response={"bridge_verified": True},
                confirmed_at=event["confirmed_at"],
            )
            return str(payment.pk)


class RefundConfirmationView(SignedBridgeView):
    secret_setting = "SETTLEMENTS_REFUND_BRIDGE_SECRET"
    serializer_class = RefundConfirmationSerializer

    def handle_event(self, event):
        payment = Payment.objects.only("provider").get(pk=event["payment_id"])
        if payment.provider != event["provider"]:
            raise DjangoValidationError("Payment provider mismatch")
        if payment.provider == Payment.ProviderChoices.MOCK and not getattr(settings, "SETTLEMENTS_ALLOW_SIGNED_MOCK_EVENTS", False):
            raise DjangoValidationError("Mock refunds are disabled")
        refund = post_verified_refund(
            payment_id=event["payment_id"],
            return_request_id=event["return_request_id"],
            confirmed_amount=event["confirmed_amount"],
            currency=event["currency"],
            gateway_reference=event["gateway_reference"],
            idempotency_key=event["idempotency_key"],
            confirmed_at=event["confirmed_at"],
            lines=[dict(item) for item in event["lines"]],
        )
        return str(refund.pk)


class PayoutConfirmationView(SignedBridgeView):
    secret_setting = "SETTLEMENTS_PAYOUT_BRIDGE_SECRET"
    serializer_class = PayoutConfirmationSerializer

    def handle_event(self, event):
        if not Seller.objects.filter(user_id=event["seller_id"], status=Seller.StatusChoices.APPROVED).exists():
            raise DjangoValidationError("Seller is not approved")
        payout = post_confirmed_payout(
            seller_id=event["seller_id"],
            currency=event["currency"],
            amount=event["amount"],
            external_reference=event["external_reference"],
            idempotency_key=event["idempotency_key"],
            confirmed_at=event["confirmed_at"],
        )
        return str(payout.pk)
