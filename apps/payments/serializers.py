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
    user_phone = serializers.ReadOnlyField(source="user.phone")

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
            "user_phone",
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
    user_phone = serializers.ReadOnlyField(source="user.phone")
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
            "user_phone",
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
    """
    Creates a new payment attempt for an order.

    Input:
    {
        "order": 1,
        "provider": "mock"
    }
    """

    order = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.all(),
    )

    provider = serializers.ChoiceField(
        choices=Payment.ProviderChoices.choices,
        default=Payment.ProviderChoices.MOCK,
    )

    def validate_order(self, order):
        """
        Check if this order can be paid.
        """

        request = self.context["request"]
        user = request.user

        # Normal user can pay only own order.
        if not (user.is_staff or user.is_superuser):
            if order.user_id != user.id:
                raise serializers.ValidationError(
                    "You cannot create payment for this order."
                )

        if order.status == Order.StatusChoices.CANCELLED:
            raise serializers.ValidationError(
                "Cannot create payment for a cancelled order."
            )

        if order.payment_status == Order.PaymentStatusChoices.PAID:
            raise serializers.ValidationError(
                "Order is already paid."
            )

        if order.total_amount <= 0:
            raise serializers.ValidationError(
                "Order total amount must be greater than zero."
            )

        return order

    def create(self, validated_data):
        """
        Create payment with amount copied from order total.
        """

        request = self.context["request"]
        order = validated_data["order"]
        provider = validated_data["provider"]

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

        if payment.status == Payment.StatusChoices.SUCCESS:
            raise serializers.ValidationError("Payment is already successful.")

        if payment.status == Payment.StatusChoices.CANCELLED:
            raise serializers.ValidationError("Cancelled payment cannot be successful.")

        if payment.status == Payment.StatusChoices.REFUNDED:
            raise serializers.ValidationError("Refunded payment cannot be successful.")

        if payment.order.status == Order.StatusChoices.CANCELLED:
            raise serializers.ValidationError("Cannot pay a cancelled order.")

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

        if payment.status == Payment.StatusChoices.SUCCESS:
            raise serializers.ValidationError(
                "Successful payment cannot be marked as failed."
            )

        if payment.status == Payment.StatusChoices.REFUNDED:
            raise serializers.ValidationError(
                "Refunded payment cannot be marked as failed."
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
            raise serializers.ValidationError(
                "Successful payment cannot be cancelled."
            )

        if payment.status == Payment.StatusChoices.REFUNDED:
            raise serializers.ValidationError(
                "Refunded payment cannot be cancelled."
            )

        if payment.status == Payment.StatusChoices.CANCELLED:
            raise serializers.ValidationError(
                "Payment is already cancelled."
            )

        return attrs