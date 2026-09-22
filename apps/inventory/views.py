from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import F
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.inventory.models import (
    Stock,
    StockMovement,
    StockTransfer,
    Warehouse,
)
from apps.inventory.permissions import (
    CanAccessInventory,
    CanAccessStockTransfers,
)
from apps.inventory.serializers import (
    StockListSerializer,
    StockMovementListSerializer,
    StockMovementSerializer,
    StockSerializer,
    StockTransferActionSerializer,
    StockTransferListSerializer,
    StockTransferSerializer,
    WarehouseListSerializer,
    WarehouseSerializer,
)


class WarehouseViewSet(viewsets.ModelViewSet):
    """
    Manage warehouses.

    Read:
        view_inventory

    Create/update/delete:
        manage_inventory
    """

    queryset = Warehouse.objects.all()
    permission_classes = [
        IsAuthenticated,
        CanAccessInventory,
    ]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    search_fields = [
        "name",
        "code",
        "city",
        "province",
        "manager_name",
    ]
    ordering_fields = [
        "name",
        "code",
        "city",
        "created_at",
        "updated_at",
    ]
    ordering = ["name"]

    def get_serializer_class(self):
        if self.action == "list":
            return WarehouseListSerializer

        return WarehouseSerializer

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="my-assignments",
    )
    def my_assignments(self, request):
        """Return the active warehouses assigned to the current user."""

        warehouses = Warehouse.objects.filter(
            is_active=True,
        )

        if not request.user.is_superuser:
            warehouses = warehouses.filter(
                memberships__user=request.user,
                memberships__is_active=True,
            )

        warehouse_ids = list(
            warehouses.order_by("id").values_list("id", flat=True).distinct()
        )

        return Response(
            {
                "warehouse_ids": warehouse_ids,
            }
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="active",
    )
    def active(self, request):
        """
        List active warehouses only.
        """

        warehouses = self.get_queryset().filter(
            is_active=True,
        )

        page = self.paginate_queryset(warehouses)

        if page is not None:
            serializer = WarehouseListSerializer(
                page,
                many=True,
            )
            return self.get_paginated_response(
                serializer.data,
            )

        serializer = WarehouseListSerializer(
            warehouses,
            many=True,
        )

        return Response(serializer.data)


class StockViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Stock record management.

    Read:
        view_inventory

    Create or update metadata:
        manage_inventory

    Quantity changes:
        StockMovement and internal business workflows

    Direct deletion and public reservation actions
    are intentionally unsupported.
    """

    queryset = Stock.objects.select_related(
        "product",
        "warehouse",
        "updated_by",
    ).all()

    permission_classes = [
        IsAuthenticated,
        CanAccessInventory,
    ]

    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

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

    ordering = [
        "product__name",
        "warehouse__name",
    ]

    def get_serializer_class(self):
        if self.action == "list":
            return StockListSerializer

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
                quantity__lte=(F("low_stock_threshold") + F("reserved_quantity"))
            )

        if in_stock in ["true", "1", "yes"]:
            queryset = queryset.filter(quantity__gt=0)

        return queryset

    def perform_create(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(
        detail=False,
        methods=["get"],
        url_path="low-stock",
    )
    def low_stock(self, request):
        """
        List stocks whose available quantity is
        below or equal to the low-stock threshold.
        """

        queryset = self.get_queryset().filter(
            quantity__lte=(F("low_stock_threshold") + F("reserved_quantity"))
        )

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = StockListSerializer(
                page,
                many=True,
            )

            return self.get_paginated_response(serializer.data)

        serializer = StockListSerializer(
            queryset,
            many=True,
        )

        return Response(serializer.data)


class StockMovementViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Append-only stock movement history.

    Read:
        view_inventory

    Create:
        manage_inventory

    Existing movements cannot be edited or deleted.
    """

    queryset = StockMovement.objects.select_related(
        "product",
        "warehouse",
        "created_by",
    ).all()

    permission_classes = [
        IsAuthenticated,
        CanAccessInventory,
    ]

    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

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
            queryset = queryset.filter(
                product_id=product_id,
            )

        if warehouse_id:
            queryset = queryset.filter(
                warehouse_id=warehouse_id,
            )

        if movement_type:
            queryset = queryset.filter(
                movement_type=movement_type,
            )

        if reference_id:
            queryset = queryset.filter(
                reference_id=reference_id,
            )

        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
        )
        serializer.is_valid(
            raise_exception=True,
        )

        try:
            self.perform_create(serializer)

        except DjangoValidationError as exc:
            if hasattr(exc, "message_dict"):
                error_data = exc.message_dict
            else:
                messages = getattr(
                    exc,
                    "messages",
                    [str(exc)],
                )

                error_data = {
                    "detail": (messages[0] if len(messages) == 1 else messages)
                }

            return Response(
                error_data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        headers = self.get_success_headers(
            serializer.data,
        )

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers,
        )

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
        )


class StockTransferViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Manage transfers between warehouses.

    Transfer workflow:
        create -> approve -> ship -> receive

    Shipping creates transfer_out from the source warehouse.
    Receiving creates transfer_in at the destination warehouse.

    Access is controlled by stock-transfer RBAC permissions.
    """

    queryset = StockTransfer.objects.select_related(
        "product",
        "from_warehouse",
        "to_warehouse",
        "requested_by",
        "approved_by",
        "shipped_by",
        "received_by",
    ).all()

    permission_classes = [
        IsAuthenticated,
        CanAccessStockTransfers,
    ]

    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

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
        "approved_at",
        "received_at",
    ]

    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return StockTransferListSerializer

        if self.action in [
            "approve",
            "ship",
            "receive",
            "cancel",
        ]:
            return StockTransferActionSerializer

        return StockTransferSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        product_id = self.request.query_params.get("product")
        from_warehouse_id = self.request.query_params.get("from_warehouse")
        to_warehouse_id = self.request.query_params.get("to_warehouse")
        transfer_status = self.request.query_params.get("status")

        if product_id:
            queryset = queryset.filter(
                product_id=product_id,
            )

        if from_warehouse_id:
            queryset = queryset.filter(
                from_warehouse_id=from_warehouse_id,
            )

        if to_warehouse_id:
            queryset = queryset.filter(
                to_warehouse_id=to_warehouse_id,
            )

        if transfer_status:
            queryset = queryset.filter(
                status=transfer_status,
            )

        return queryset

    def perform_create(self, serializer):
        serializer.save(
            requested_by=self.request.user,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="approve",
    )
    def approve(
        self,
        request,
        pk=None,
    ):
        """Approve a pending stock transfer."""

        transfer = self.get_object()

        try:
            transfer.approve(
                user=request.user,
            )
            transfer.refresh_from_db()

        except DjangoValidationError as exc:
            return Response(
                {"detail": (exc.messages if hasattr(exc, "messages") else str(exc))},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = StockTransferSerializer(
            transfer,
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="ship",
    )
    def ship(
        self,
        request,
        pk=None,
    ):
        """Ship an approved transfer from the source warehouse."""

        transfer = self.get_object()

        serializer = StockTransferActionSerializer(
            data=request.data,
        )
        serializer.is_valid(
            raise_exception=True,
        )

        tracking_number = serializer.validated_data.get("tracking_number")

        try:
            transfer.ship(
                user=request.user,
                tracking_number=tracking_number,
            )
            transfer.refresh_from_db()

        except DjangoValidationError as exc:
            return Response(
                {"detail": (exc.messages if hasattr(exc, "messages") else str(exc))},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = StockTransferSerializer(
            transfer,
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="receive",
    )
    def receive(
        self,
        request,
        pk=None,
    ):
        """Receive an in-transit transfer at the destination warehouse."""

        transfer = self.get_object()

        try:
            transfer.receive(
                user=request.user,
            )
            transfer.refresh_from_db()

        except DjangoValidationError as exc:
            return Response(
                {"detail": (exc.messages if hasattr(exc, "messages") else str(exc))},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = StockTransferSerializer(
            transfer,
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="cancel",
    )
    def cancel(
        self,
        request,
        pk=None,
    ):
        """Cancel a pending or approved stock transfer."""

        transfer = self.get_object()

        try:
            transfer.cancel(
                user=request.user,
            )
            transfer.refresh_from_db()

        except DjangoValidationError as exc:
            return Response(
                {"detail": (exc.messages if hasattr(exc, "messages") else str(exc))},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = StockTransferSerializer(
            transfer,
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )
