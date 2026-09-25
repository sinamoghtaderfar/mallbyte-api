from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.orders.models import Order
from apps.shipping.models import Shipment
from apps.shipping.serializers import (
    EligibleShipmentOrderSerializer,
    ShipmentCancelSerializer,
    ShipmentCreateSerializer,
    ShipmentDetailSerializer,
    ShipmentListSerializer,
    ShipmentMarkDeliveredSerializer,
    ShipmentMarkReadySerializer,
    ShipmentMarkShippedSerializer,
)
from apps.shipping.services import create_shipment_notification


class ShipmentViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create and manage shipments without mixing sellers in an order.

    Endpoints:
      GET  /api/shipping/shipments/
      POST /api/shipping/shipments/
      GET  /api/shipping/shipments/eligible-orders/
      GET  /api/shipping/shipments/{id}/
      POST /api/shipping/shipments/{id}/mark-ready/
      POST /api/shipping/shipments/{id}/mark-shipped/
      POST /api/shipping/shipments/{id}/mark-delivered/
      POST /api/shipping/shipments/{id}/cancel/
    """

    permission_classes = [IsAuthenticated]

    queryset = Shipment.objects.select_related(
        "order",
        "user",
        "created_by",
        "seller_fulfillment",
        "seller_fulfillment__seller",
    ).prefetch_related("events")

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "shipment_number",
        "order__order_number",
        "user__phone",
        "user__email",
        "seller_fulfillment__seller__email",
        "seller_fulfillment__seller__full_name",
        "tracking_number",
        "receiver_name",
        "receiver_phone",
        "city",
        "postal_code",
    ]
    ordering_fields = [
        "created_at",
        "updated_at",
        "shipped_at",
        "delivered_at",
        "status",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        """Staff can see every shipment; buyers only their own shipments."""
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return queryset
        return queryset.filter(user=user)

    def get_serializer_class(self):
        if self.action == "list":
            return ShipmentListSerializer
        if self.action == "eligible_orders":
            return EligibleShipmentOrderSerializer
        if self.action == "create":
            return ShipmentCreateSerializer
        if self.action == "mark_ready":
            return ShipmentMarkReadySerializer
        if self.action == "mark_shipped":
            return ShipmentMarkShippedSerializer
        if self.action == "mark_delivered":
            return ShipmentMarkDeliveredSerializer
        if self.action == "cancel":
            return ShipmentCancelSerializer
        return ShipmentDetailSerializer

    @staticmethod
    def _is_staff_user(user):
        return user.is_staff or user.is_superuser

    @staticmethod
    def _staff_required_response():
        return Response(
            {"detail": "Only staff users can manage shipments."},
            status=status.HTTP_403_FORBIDDEN,
        )

    @staticmethod
    def _validation_error_response(exc):
        return Response(
            {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @staticmethod
    def _notify(shipment, template_key):
        create_shipment_notification(
            shipment=shipment,
            template_key=template_key,
            order_id=shipment.order.order_number,
        )

    @action(detail=False, methods=["get"], url_path="eligible-orders")
    def eligible_orders(self, request):
        """Paid orders with at least one seller lacking an active shipment.

        A multi-seller order remains eligible after its first seller receives a
        shipment. Older orders without order items retain the one-shipment rule.
        """
        if not self._is_staff_user(request.user):
            return self._staff_required_response()

        orders = (
            Order.objects.select_related("user")
            .prefetch_related("items__product__seller", "seller_fulfillments")
            .filter(
                status__in=[
                    Order.StatusChoices.PAID,
                    Order.StatusChoices.PROCESSING,
                ],
                payment_status=Order.PaymentStatusChoices.PAID,
            )
            .order_by("-paid_at", "-created_at")
        )

        # Keep legacy (item-less) orders available until they have a shipment;
        # orders with items are available while any seller can still ship.
        eligible = []
        excluded_statuses = [
            Shipment.StatusChoices.CANCELLED,
            Shipment.StatusChoices.RETURNED,
        ]
        seller_serializer = EligibleShipmentOrderSerializer(
            context={"request": request}
        )
        for order in orders:
            if order.items.exists():
                if seller_serializer.get_eligible_sellers(order):
                    eligible.append(order)
                continue

            has_active_shipment = (
                Shipment.objects.filter(order=order)
                .exclude(status__in=excluded_statuses)
                .exists()
            )
            if not has_active_shipment:
                eligible.append(order)

        serializer = self.get_serializer(eligible, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        """Create one shipment for the selected seller's part of a paid order.

        For a multi-seller order, supply `seller` with the seller's user ID.
        For a single-seller order the seller is inferred by the serializer.
        """
        if not self._is_staff_user(request.user):
            return self._staff_required_response()

        serializer = self.get_serializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        # ShipmentCreateSerializer delegates to the model's atomic helper and
        # converts its validation errors into DRF validation errors.
        shipment = serializer.save()
        self._notify(shipment, "shipment_created")
        return Response(
            ShipmentDetailSerializer(shipment).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="mark-ready")
    def mark_ready(self, request, pk=None):
        if not self._is_staff_user(request.user):
            return self._staff_required_response()

        shipment = self.get_object()
        serializer = ShipmentMarkReadySerializer(
            data=request.data,
            context={"shipment": shipment},
        )
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data.get("note", "")

        try:
            # The model updates this shipment, its seller fulfillment and the
            # aggregate order status in one transaction.
            shipment.mark_ready(user=request.user, note=note)
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        shipment.refresh_from_db()
        self._notify(shipment, "shipment_ready")
        return Response(
            ShipmentDetailSerializer(shipment).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="mark-shipped")
    def mark_shipped(self, request, pk=None):
        if not self._is_staff_user(request.user):
            return self._staff_required_response()

        shipment = self.get_object()
        serializer = ShipmentMarkShippedSerializer(
            data=request.data,
            context={"shipment": shipment},
        )
        serializer.is_valid(raise_exception=True)

        try:
            shipment.mark_shipped(
                tracking_number=serializer.validated_data.get("tracking_number", ""),
                tracking_url=serializer.validated_data.get("tracking_url", ""),
                user=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        shipment.refresh_from_db()
        self._notify(shipment, "shipment_shipped")
        return Response(
            ShipmentDetailSerializer(shipment).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="mark-delivered")
    def mark_delivered(self, request, pk=None):
        if not self._is_staff_user(request.user):
            return self._staff_required_response()

        shipment = self.get_object()
        serializer = ShipmentMarkDeliveredSerializer(
            data=request.data,
            context={"shipment": shipment},
        )
        serializer.is_valid(raise_exception=True)

        try:
            shipment.mark_delivered(
                user=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        shipment.refresh_from_db()
        self._notify(shipment, "shipment_delivered")
        return Response(
            ShipmentDetailSerializer(shipment).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        if not self._is_staff_user(request.user):
            return self._staff_required_response()

        shipment = self.get_object()
        serializer = ShipmentCancelSerializer(
            data=request.data,
            context={"shipment": shipment},
        )
        serializer.is_valid(raise_exception=True)

        try:
            shipment.cancel(
                user=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            return self._validation_error_response(exc)

        shipment.refresh_from_db()
        self._notify(shipment, "shipment_cancelled")
        return Response(
            ShipmentDetailSerializer(shipment).data,
            status=status.HTTP_200_OK,
        )
