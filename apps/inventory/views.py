from rest_framework import decorators, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Stock, StockMovement, StockTransfer, Warehouse
from .serializers import (
    StockMovementSerializer,
    StockSerializer,
    StockTransferSerializer,
    WarehouseSerializer,
)


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class StockViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Stock.objects.select_related("product", "warehouse")
    serializer_class = StockSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()

        warehouse_id = self.request.query_params.get("warehouse")
        product_id = self.request.query_params.get("product")
        low_stock = self.request.query_params.get("low_stock")

        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        if low_stock in {"1", "true", "True"}:
            queryset = queryset.filter(quantity__lte=5)

        return queryset


class StockMovementViewSet(viewsets.ModelViewSet):
    queryset = StockMovement.objects.select_related("product", "warehouse", "created_by")
    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()

        warehouse_id = self.request.query_params.get("warehouse")
        product_id = self.request.query_params.get("product")
        movement_type = self.request.query_params.get("type")

        if warehouse_id:
            queryset = queryset.filter(warehouse_id=warehouse_id)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        if movement_type:
            queryset = queryset.filter(movement_type=movement_type)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class StockTransferViewSet(viewsets.ModelViewSet):
    queryset = StockTransfer.objects.select_related(
        "product", "from_warehouse", "to_warehouse", "requested_by", "approved_by"
    )
    serializer_class = StockTransferSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)

    @decorators.action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        transfer = self.get_object()

        if transfer.status == StockTransfer.StatusChoices.COMPLETED:
            return Response(
                {"detail": "Transfer is already completed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        outgoing = StockMovement.objects.create(
            product=transfer.product,
            warehouse=transfer.from_warehouse,
            movement_type=StockMovement.MovementType.TRANSFER_OUT,
            quantity=-transfer.quantity,
            reference_id=f"transfer:{transfer.id}",
            reason=transfer.reason,
            created_by=request.user,
        )

        incoming = StockMovement.objects.create(
            product=transfer.product,
            warehouse=transfer.to_warehouse,
            movement_type=StockMovement.MovementType.TRANSFER_IN,
            quantity=transfer.quantity,
            reference_id=f"transfer:{transfer.id}",
            reason=transfer.reason,
            created_by=request.user,
        )

        transfer.status = StockTransfer.StatusChoices.COMPLETED
        transfer.approved_by = request.user
        transfer.save(update_fields=["status", "approved_by", "updated_at"])

        return Response(
            {
                "detail": "Transfer completed successfully.",
                "transfer_id": transfer.id,
                "outgoing_movement_id": outgoing.id,
                "incoming_movement_id": incoming.id,
            },
            status=status.HTTP_200_OK,
        )
