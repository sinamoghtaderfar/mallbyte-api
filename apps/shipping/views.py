#Create shipment from paid order
#List shipments
#Retrieve shipment detail
#Mark ready
#Mark shipped
#Mark delivered
#Cancel shipment

from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.shipping.models import Shipment
from apps.shipping.serializers import (
    ShipmentCancelSerializer,
    ShipmentCreateSerializer,
    ShipmentDetailSerializer,
    ShipmentListSerializer,
    ShipmentMarkDeliveredSerializer,
    ShipmentMarkReadySerializer,
    ShipmentMarkShippedSerializer,
)


class ShipmentViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Shipment API.

    Main endpoints:
    - GET    /api/shipping/shipments/
    - POST   /api/shipping/shipments/
    - GET    /api/shipping/shipments/{id}/
    - POST   /api/shipping/shipments/{id}/mark-ready/
    - POST   /api/shipping/shipments/{id}/mark-shipped/
    - POST   /api/shipping/shipments/{id}/mark-delivered/
    - POST   /api/shipping/shipments/{id}/cancel/
    """

    permission_classes = [IsAuthenticated]

    queryset = Shipment.objects.select_related(
        "order",
        "user",
        "created_by",
    ).prefetch_related(
        "events",
    )

    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    search_fields = [
        "shipment_number",
        "order__order_number",
        "user__phone",
        "user__email",
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
        """
        Staff users can see all shipments.
        Normal users can see only their own shipments.
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
            return ShipmentListSerializer

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

    def _is_staff_user(self, user):
        """
        Check whether user can manage shipments.
        Later we can replace this with RBAC permission.
        """

        return user.is_staff or user.is_superuser

    def _staff_required_response(self):
        """
        Response for users who are not allowed to manage shipments.
        """

        return Response(
            {"detail": "Only staff users can manage shipments."},
            status=status.HTTP_403_FORBIDDEN,
        )

    def create(self, request, *args, **kwargs):
        """
        Create shipment from a paid order.

        Example input:
        {
            "order": 1,
            "carrier": "dhl"
        }
        """

        if not self._is_staff_user(request.user):
            return self._staff_required_response()

        serializer = self.get_serializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        shipment = serializer.save()

        response_serializer = ShipmentDetailSerializer(shipment)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="mark-ready")
    def mark_ready(self, request, pk=None):
        """
        Mark shipment as ready to ship.

        Example input:
        {
            "note": "Package prepared"
        }
        """

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
            shipment.mark_ready(
                user=request.user,
                note=note,
            )
            shipment.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = ShipmentDetailSerializer(shipment)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="mark-shipped")
    def mark_shipped(self, request, pk=None):
        """
        Mark shipment as shipped.

        Example input:
        {
            "tracking_number": "DHL123456",
            "tracking_url": "https://tracking.example.com/DHL123456",
            "note": "Package handed to carrier"
        }
        """

        if not self._is_staff_user(request.user):
            return self._staff_required_response()

        shipment = self.get_object()

        serializer = ShipmentMarkShippedSerializer(
            data=request.data,
            context={"shipment": shipment},
        )
        serializer.is_valid(raise_exception=True)

        tracking_number = serializer.validated_data.get("tracking_number", "")
        tracking_url = serializer.validated_data.get("tracking_url", "")
        note = serializer.validated_data.get("note", "")

        try:
            shipment.mark_shipped(
                tracking_number=tracking_number,
                tracking_url=tracking_url,
                user=request.user,
                note=note,
            )
            shipment.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = ShipmentDetailSerializer(shipment)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="mark-delivered")
    def mark_delivered(self, request, pk=None):
        """
        Mark shipment as delivered.

        Example input:
        {
            "note": "Delivered to customer"
        }
        """

        if not self._is_staff_user(request.user):
            return self._staff_required_response()

        shipment = self.get_object()

        serializer = ShipmentMarkDeliveredSerializer(
            data=request.data,
            context={"shipment": shipment},
        )
        serializer.is_valid(raise_exception=True)

        note = serializer.validated_data.get("note", "")

        try:
            shipment.mark_delivered(
                user=request.user,
                note=note,
            )
            shipment.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = ShipmentDetailSerializer(shipment)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        """
        Cancel shipment.

        Example input:
        {
            "note": "Shipment cancelled by admin"
        }
        """

        if not self._is_staff_user(request.user):
            return self._staff_required_response()

        shipment = self.get_object()

        serializer = ShipmentCancelSerializer(
            data=request.data,
            context={"shipment": shipment},
        )
        serializer.is_valid(raise_exception=True)

        note = serializer.validated_data.get("note", "")

        try:
            shipment.cancel(
                user=request.user,
                note=note,
            )
            shipment.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = ShipmentDetailSerializer(shipment)
        return Response(response_serializer.data, status=status.HTTP_200_OK)