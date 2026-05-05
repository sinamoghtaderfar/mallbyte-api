from rest_framework import serializers

from .models import Stock, StockMovement, StockTransfer, Warehouse


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at", "created_by")


class StockSerializer(serializers.ModelSerializer):
    available_quantity = serializers.IntegerField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Stock
        fields = "__all__"
        read_only_fields = ("last_updated", "updated_by")


class StockMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = "__all__"
        read_only_fields = ("before_quantity", "after_quantity", "created_at", "created_by")

    def validate(self, attrs):
        product = attrs["product"]
        warehouse = attrs["warehouse"]
        quantity = attrs["quantity"]
        movement_type = attrs["movement_type"]

        outgoing_types = {
            StockMovement.MovementType.SALE,
            StockMovement.MovementType.TRANSFER_OUT,
            StockMovement.MovementType.DAMAGED,
        }

        if movement_type in outgoing_types and quantity >= 0:
            raise serializers.ValidationError(
                {"quantity": "Outgoing movement quantity must be negative."}
            )

        if movement_type == StockMovement.MovementType.PURCHASE and quantity <= 0:
            raise serializers.ValidationError(
                {"quantity": "Purchase movement quantity must be positive."}
            )

        stock = Stock.objects.filter(product=product, warehouse=warehouse).first()
        current_quantity = stock.quantity if stock else 0

        if current_quantity + quantity < 0:
            raise serializers.ValidationError(
                {"quantity": "Insufficient stock for this movement."}
            )

        return attrs


class StockTransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockTransfer
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at", "approved_by")

    def validate(self, attrs):
        if attrs["from_warehouse"] == attrs["to_warehouse"]:
            raise serializers.ValidationError(
                {"to_warehouse": "Source and destination warehouse cannot be the same."}
            )
        if attrs["quantity"] <= 0:
            raise serializers.ValidationError(
                {"quantity": "Transfer quantity must be greater than zero."}
            )
        return attrs
