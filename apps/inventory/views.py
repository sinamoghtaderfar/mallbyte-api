from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import F
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from urllib3 import request

from apps.inventory.models import Stock, StockMovement, StockTransfer, Warehouse
from apps.inventory.serializers import (
    StockListSerializer,
    StockMovementListSerializer,
    StockMovementSerializer,
    StockReleaseReservationSerializer,
    StockReserveSerializer,
    StockSerializer,
    StockTransferActionSerializer,
    StockTransferListSerializer,
    StockTransferSerializer,
    WarehouseListSerializer,
    WarehouseSerializer,
)
from apps.rbac.permissions import IsProductAdmin


class WarehouseViewSet(viewsets.ModelViewSet):
    """
    Manage warehouses.
    Only product admins / superusers should manage inventory warehouses.
    """

    queryset = Warehouse.objects.all()
    permission_classes = [IsAuthenticated, IsProductAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "code", "city", "province", "manager_name"]
    ordering_fields = ["name", "code", "city", "created_at", "updated_at"]
    ordering = ["name"]

    def get_serializer_class(self):
        if self.action == "list":
            return WarehouseListSerializer
        return WarehouseSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request):
        """List active warehouses only."""
        warehouses = self.get_queryset().filter(is_active=True)
        page = self.paginate_queryset(warehouses)

        if page is not None:
            serializer = WarehouseListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = WarehouseListSerializer(warehouses, many=True)
        return Response(serializer.data)


class StockViewSet(viewsets.ModelViewSet):
    """
    Manage stock records.
    Stock is per product per warehouse.
    """

    queryset = Stock.objects.select_related(
        "product",
        "warehouse",
        "updated_by",
    ).all()
    permission_classes = [IsAuthenticated, IsProductAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "product__name",
        "product__sku",
        "warehouse__name",
        "warehouse__code",
        "aisle",
        "shelf",
        "bin_code",
    ]
    ordering_fields = [
        "quantity",
        "reserved_quantity",
        "low_stock_threshold",
        "last_updated",
    ]
    ordering = ["product__name", "warehouse__name"]

    def get_serializer_class(self):
        if self.action == "list":
            return StockListSerializer

        if self.action == "reserve":
            return StockReserveSerializer

        if self.action == "release_reservation":
            return StockReleaseReservationSerializer

        return StockSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        product_id = self.request.query_params.get("product")
        warehouse_id = self.request.query_params.get("warehouse")
        low_stock = self.request.query_params.get("low_stock")
        in_stock = self.request.query_params.get("in_stock")

        if product_id:
            queryset = queryset.filter(product_id=product_id)

        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)

        if low_stock in ["true", "1", "yes"]:
            queryset = queryset.filter(
                quantity__lte=F("low_stock_threshold") + F("reserved_quantity")
            )

        if in_stock in ["true", "1", "yes"]:
            queryset = queryset.filter(quantity__gt=0)

        return queryset

    def perform_create(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        """List stock records where available quantity is low."""
        queryset = self.get_queryset().filter(
            quantity__lte=F("low_stock_threshold") + F("reserved_quantity")
        )

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = StockListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StockListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="reserve")
    def reserve(self, request):
        """Reserve stock for a pending order."""
        serializer = StockReserveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        stock = serializer.validated_data["stock"]
        quantity = serializer.validated_data["quantity"]

        try:
            stock.reserve(quantity=quantity, user=request.user)
            stock.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = StockSerializer(stock)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="release-reservation")
    def release_reservation(self, request):
        """Release reserved stock."""
        serializer = StockReleaseReservationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        stock = serializer.validated_data["stock"]
        quantity = serializer.validated_data["quantity"]

        try:
            stock.release_reservation(quantity=quantity, user=request.user)
            stock.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = StockSerializer(stock)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class StockMovementViewSet(viewsets.ModelViewSet):
    """
    Manage stock movements.
    Every stock increase/decrease is recorded here.
    """

    queryset = StockMovement.objects.select_related(
        "product",
        "warehouse",
        "created_by",
    ).all()
    permission_classes = [IsAuthenticated, IsProductAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "product__name",
        "product__sku",
        "warehouse__name",
        "warehouse__code",
        "reference_id",
        "reason",
        "notes",
    ]
    ordering_fields = [
        "created_at",
        "quantity",
        "before_quantity",
        "after_quantity",
    ]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return StockMovementListSerializer
        return StockMovementSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        product_id = self.request.query_params.get("product")
        warehouse_id = self.request.query_params.get("warehouse")
        movement_type = self.request.query_params.get("movement_type")
        reference_id = self.request.query_params.get("reference_id")

        if product_id:
            queryset = queryset.filter(product_id=product_id)

        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)

        if movement_type:
            queryset = queryset.filter(movement_type=movement_type)

        if reference_id:
            queryset = queryset.filter(reference_id=reference_id)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class StockTransferViewSet(viewsets.ModelViewSet):
    """
    Manage transfers between warehouses.
    Completing a transfer creates two stock movements:
    transfer_out and transfer_in.
    """

    queryset = StockTransfer.objects.select_related(
        "product",
        "from_warehouse",
        "to_warehouse",
        "requested_by",
        "approved_by",
    ).all()
    permission_classes = [IsAuthenticated, IsProductAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "product__name",
        "product__sku",
        "from_warehouse__name",
        "from_warehouse__code",
        "to_warehouse__name",
        "to_warehouse__code",
        "tracking_number",
        "reason",
    ]
    ordering_fields = [
        "created_at",
        "updated_at",
        "quantity",
        "status",
        "shipped_at",
        "delivered_at",
    ]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return StockTransferListSerializer

        if self.action in ["mark_in_transit", "complete", "cancel"]:
            return StockTransferActionSerializer

        return StockTransferSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        product_id = self.request.query_params.get("product")
        from_warehouse_id = self.request.query_params.get("from_warehouse")
        to_warehouse_id = self.request.query_params.get("to_warehouse")
        transfer_status = self.request.query_params.get("status")

        if product_id:
            queryset = queryset.filter(product_id=product_id)

        if from_warehouse_id:
            queryset = queryset.filter(from_warehouse_id=from_warehouse_id)

        if to_warehouse_id:
            queryset = queryset.filter(to_warehouse_id=to_warehouse_id)

        if transfer_status:
            queryset = queryset.filter(status=transfer_status)

        return queryset

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="mark-in-transit")
    def mark_in_transit(self, request, pk=None):
        """Mark transfer as in transit."""
        transfer = self.get_object()

        serializer = StockTransferActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tracking_number = serializer.validated_data.get("tracking_number")

        try:
            transfer.mark_in_transit(
                user=request.user,
                tracking_number=tracking_number,
            )
            transfer.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = StockTransferSerializer(transfer)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        """
        Complete transfer.
        This creates transfer_out and transfer_in stock movements.
        """
        transfer = self.get_object()

        try:
            transfer.complete(user=request.user)
            transfer.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = StockTransferSerializer(transfer)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        """Cancel transfer if it is not completed."""
        transfer = self.get_object()

        try:
            transfer.cancel()
            transfer.refresh_from_db()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = StockTransferSerializer(transfer)
        return Response(response_serializer.data, status=status.HTTP_200_OK)