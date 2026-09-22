from django.db import transaction
from rest_framework import serializers

from apps.orders.models import Order
from apps.payments.models import Payment, PaymentEvent

# ============================================================
# Payment Event Serializer
# ============================================================


class PaymentEventSerializer(serializers.ModelSerializer):
    """
    Shows payment history/events.

    Example:
    pending -> success
    pending -> failed
    gateway callback received
    """

    created_by_name = serializers.ReadOnlyField(source="created_by.full_name")

    class Meta:
        model = PaymentEvent
        fields = [
            "id",
            "event_type",
            "old_status",
            "new_status",
            "message",
            "data",
            "created_by",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = fields


# ============================================================
# Payment List Serializer
# ============================================================


class PaymentListSerializer(serializers.ModelSerializer):
    """
    Small serializer for payment list.
    """

    order_number = serializers.ReadOnlyField(source="order.order_number")
    user_email = serializers.ReadOnlyField(source="user.email")

    provider_display = serializers.CharField(
        source="get_provider_display",
        read_only=True,
    )
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    class Meta:
        model = Payment
        fields = [
            "id",
            "payment_number",
            "order",
            "order_number",
            "user",
            "user_email",
            "provider",
            "provider_display",
            "status",
            "status_display",
            "amount",
            "currency",
            "created_at",
            "paid_at",
        ]
        read_only_fields = fields


# ============================================================
# Payment Detail Serializer
# ============================================================


class PaymentDetailSerializer(serializers.ModelSerializer):
    """
    Full payment detail with events.
    """

    order_number = serializers.ReadOnlyField(source="order.order_number")
    user_email = serializers.ReadOnlyField(source="user.email")
    user_full_name = serializers.ReadOnlyField(source="user.full_name")

    provider_display = serializers.CharField(
        source="get_provider_display",
        read_only=True,
    )
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    events = PaymentEventSerializer(many=True, read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "payment_number",
            "order",
            "order_number",
            "user",
            "user_email",
            "user_full_name",
            "provider",
            "provider_display",
            "status",
            "status_display",
            "amount",
            "currency",
            "gateway_reference",
            "gateway_response",
            "failure_reason",
            "paid_at",
            "failed_at",
            "cancelled_at",
            "refunded_at",
            "created_by",
            "created_at",
            "updated_at",
            "events",
        ]
        read_only_fields = fields


# ============================================================
# Payment Create Serializer
# ============================================================


class PaymentCreateSerializer(serializers.Serializer):
    order = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.all(),
    )

    # Real gateways need their own verified callback flow.
    # The public demo endpoint currently supports mock only.
    provider = serializers.ChoiceField(
        choices=[
            (Payment.ProviderChoices.MOCK, "Mock Payment"),
        ],
        default=Payment.ProviderChoices.MOCK,
    )

    def validate_order(self, order):
        request = self.context["request"]
        user = request.user

        if not (user.is_staff or user.is_superuser):
            if order.user_id != user.pk:
                raise serializers.ValidationError("You cannot pay for this order.")

        if (
            order.status != Order.StatusChoices.PENDING_PAYMENT
            or order.payment_status
            not in {
                Order.PaymentStatusChoices.UNPAID,
                Order.PaymentStatusChoices.FAILED,
            }
        ):
            raise serializers.ValidationError(
                "This order is no longer awaiting payment."
            )

        if order.total_amount <= 0:
            raise serializers.ValidationError("Order total must be greater than zero.")

        return order

    def create(self, validated_data):
        request = self.context["request"]
        provider = validated_data["provider"]

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=validated_data["order"].pk)

            # Recheck after obtaining the lock.
            self.validate_order(order)

            existing = (
                Payment.objects.filter(
                    order=order,
                    provider=provider,
                    status=Payment.StatusChoices.PENDING,
                )
                .order_by("-created_at", "-pk")
                .first()
            )

            if existing:
                if existing.amount != order.total_amount:
                    raise serializers.ValidationError(
                        "The active payment amount no longer "
                        "matches the order total."
                    )

                return existing

            payment = Payment.objects.create(
                order=order,
                user=order.user,
                provider=provider,
                amount=order.total_amount,
                currency="IRR",
                created_by=request.user,
            )

            PaymentEvent.objects.create(
                payment=payment,
                event_type="payment_created",
                old_status="",
                new_status=payment.status,
                message="Payment attempt created.",
                created_by=request.user,
                data={
                    "order_number": order.order_number,
                    "amount": str(payment.amount),
                    "provider": payment.provider,
                },
            )

            return payment


# ============================================================
# Payment Success Serializer
# ============================================================


class PaymentSuccessSerializer(serializers.Serializer):
    """
    Marks a payment as successful.

    This is a mock/manual success action for now.
    Later real gateway callback will call similar logic.

    Input:
    {
        "gateway_reference": "MOCK-123",
        "gateway_response": {"status": "ok"}
    }
    """

    gateway_reference = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
    )

    gateway_response = serializers.JSONField(
        required=False,
        default=dict,
    )

    def validate(self, attrs):
        payment = self.context["payment"]

        if payment.provider != Payment.ProviderChoices.MOCK:
            raise serializers.ValidationError(
                "Only mock payments can be completed manually."
            )

        if payment.status != Payment.StatusChoices.PENDING:
            raise serializers.ValidationError("Only pending payments can be completed.")

        return attrs


# ============================================================
# Payment Fail Serializer
# ============================================================


class PaymentFailSerializer(serializers.Serializer):
    """
    Marks a payment as failed.

    Input:
    {
        "reason": "Gateway declined payment",
        "gateway_response": {"error": "declined"}
    }
    """

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    gateway_response = serializers.JSONField(
        required=False,
        default=dict,
    )

    def validate(self, attrs):
        payment = self.context["payment"]

        if payment.status != Payment.StatusChoices.PENDING:
            raise serializers.ValidationError(
                "Only pending payments can be marked as failed."
            )

        return attrs


# ============================================================
# Payment Cancel Serializer
# ============================================================


class PaymentCancelSerializer(serializers.Serializer):
    """
    Cancels a pending/failed payment attempt.

    Input:
    {
        "reason": "User cancelled payment"
    }
    """

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        payment = self.context["payment"]

        if payment.status == Payment.StatusChoices.SUCCESS:
            raise serializers.ValidationError("Successful payment cannot be cancelled.")

        if payment.status == Payment.StatusChoices.REFUNDED:
            raise serializers.ValidationError("Refunded payment cannot be cancelled.")

        if payment.status == Payment.StatusChoices.CANCELLED:
            raise serializers.ValidationError("Payment is already cancelled.")

        return attrs
