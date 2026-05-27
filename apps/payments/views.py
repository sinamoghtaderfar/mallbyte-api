# apps/payments/views.py

from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.payments.models import Payment, PaymentEvent
from apps.payments.serializers import (
    PaymentCancelSerializer,
    PaymentCreateSerializer,
    PaymentDetailSerializer,
    PaymentFailSerializer,
    PaymentListSerializer,
    PaymentSuccessSerializer,
)


class PaymentViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Payment API.

    Main endpoints:
    - GET    /api/payments/payments/
    - POST   /api/payments/payments/
    - GET    /api/payments/payments/{id}/
    - POST   /api/payments/payments/{id}/mark-success/
    - POST   /api/payments/payments/{id}/mark-failed/
    - POST   /api/payments/payments/{id}/cancel/
    """

    permission_classes = [IsAuthenticated]

    queryset = Payment.objects.select_related(
        "order",
        "user",
        "created_by",
    ).prefetch_related(
        "events",
    )

    def get_queryset(self):
        """
        Normal users can see only their own payments.
        Staff and superusers can see all payments.
        """

        user = self.request.user
        queryset = super().get_queryset()

        if user.is_staff or user.is_superuser:
            return queryset

        return queryset.filter(user=user)

    def get_serializer_class(self):
        """
        Choose serializer based on action.
        """

        if self.action == "list":
            return PaymentListSerializer

        if self.action == "create":
            return PaymentCreateSerializer

        if self.action == "mark_success":
            return PaymentSuccessSerializer

        if self.action == "mark_failed":
            return PaymentFailSerializer

        if self.action == "cancel":
            return PaymentCancelSerializer

        return PaymentDetailSerializer

    def create(self, request, *args, **kwargs):
        """
        Create a new payment attempt for an order.

        Example input:
        {
            "order": 1,
            "provider": "mock"
        }
        """

        serializer = self.get_serializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        payment = serializer.save()

        response_serializer = PaymentDetailSerializer(payment)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="mark-success")
    def mark_success(self, request, pk=None):
        """
        Mark payment as successful.

        For now this is a mock/manual success action.
        Later, real payment gateway callback can call the same logic.
        """

        payment = self.get_object()
        old_status = payment.status

        serializer = PaymentSuccessSerializer(
            data=request.data,
            context={"payment": payment},
        )
        serializer.is_valid(raise_exception=True)

        gateway_reference = serializer.validated_data.get("gateway_reference", "")
        gateway_response = serializer.validated_data.get("gateway_response", {})

        try:
            payment.mark_success(
                gateway_reference=gateway_reference,
                gateway_response=gateway_response,
            )
            payment.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        PaymentEvent.objects.create(
            payment=payment,
            event_type="payment_success",
            old_status=old_status,
            new_status=payment.status,
            message="Payment marked as successful.",
            created_by=request.user,
            data={
                "gateway_reference": gateway_reference,
                "gateway_response": gateway_response,
            },
        )

        response_serializer = PaymentDetailSerializer(payment)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="mark-failed")
    def mark_failed(self, request, pk=None):
        """
        Mark payment as failed.

        Important:
        Failed payment does not cancel the order.
        User can try another payment attempt later.
        """

        payment = self.get_object()
        old_status = payment.status

        serializer = PaymentFailSerializer(
            data=request.data,
            context={"payment": payment},
        )
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get("reason", "")
        gateway_response = serializer.validated_data.get("gateway_response", {})

        try:
            payment.mark_failed(
                reason=reason,
                gateway_response=gateway_response,
            )
            payment.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        PaymentEvent.objects.create(
            payment=payment,
            event_type="payment_failed",
            old_status=old_status,
            new_status=payment.status,
            message=reason or "Payment marked as failed.",
            created_by=request.user,
            data={
                "gateway_response": gateway_response,
            },
        )

        response_serializer = PaymentDetailSerializer(payment)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        """
        Cancel a payment attempt.

        This only cancels the payment attempt.
        It does not cancel the order.
        """

        payment = self.get_object()
        old_status = payment.status

        serializer = PaymentCancelSerializer(
            data=request.data,
            context={"payment": payment},
        )
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get("reason", "")

        try:
            payment.cancel(reason=reason)
            payment.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        PaymentEvent.objects.create(
            payment=payment,
            event_type="payment_cancelled",
            old_status=old_status,
            new_status=payment.status,
            message=reason or "Payment cancelled.",
            created_by=request.user,
            data={},
        )

        response_serializer = PaymentDetailSerializer(payment)
        return Response(response_serializer.data, status=status.HTTP_200_OK)