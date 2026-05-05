from rest_framework import serializers

from apps.inventory.models import Warehouse, Stock, StockMovement, StockTransfer
from apps.products.models import Product


class WarehouseSerializer(serializers.ModelSerializer):
    """Serializer for creating, updating, and listing warehouses."""

    created_by_name = serializers.ReadOnlyField(source="created_by.full_name")
    type_display = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = Warehouse
        fields = [
            "id",
            "name",
            "code",
            "type",
            "type_display",
            "province",
            "city",
            "address",
            "postal_code",
            "phone",
            "email",
            "manager_name",
            "manager_phone",
            "is_active",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        ]

    def validate_code(self, value):
        return value.upper().strip()


class WarehouseListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for warehouse lists."""

    type_display = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = Warehouse
        fields = [
            "id",
            "name",
            "code",
            "type",
            "type_display",
            "city",
            "is_active",
        ]


class StockSerializer(serializers.ModelSerializer):
    """Serializer for stock records."""

    product_name = serializers.ReadOnlyField(source="product.name")
    product_sku = serializers.ReadOnlyField(source="product.sku")
    warehouse_name = serializers.ReadOnlyField(source="warehouse.name")
    warehouse_code = serializers.ReadOnlyField(source="warehouse.code")
    available_quantity = serializers.IntegerField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    updated_by_name = serializers.ReadOnlyField(source="updated_by.full_name")

    class Meta:
        model = Stock
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "warehouse",
            "warehouse_name",
            "warehouse_code",
            "quantity",
            "reserved_quantity",
            "available_quantity",
            "low_stock_threshold",
            "is_low_stock",
            "aisle",
            "shelf",
            "bin_code",
            "updated_by",
            "updated_by_name",
            "last_updated",
        ]
        read_only_fields = [
            "id",
            "available_quantity",
            "is_low_stock",
            "updated_by",
            "updated_by_name",
            "last_updated",
        ]

    def validate(self, attrs):
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", 0))
        reserved_quantity = attrs.get(
            "reserved_quantity",
            getattr(self.instance, "reserved_quantity", 0),
        )

        if reserved_quantity > quantity:
            raise serializers.ValidationError(
                {
                    "reserved_quantity": "Reserved quantity cannot be greater than total quantity."
                }
            )

        return attrs


class StockListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for stock lists."""

    product_name = serializers.ReadOnlyField(source="product.name")
    product_sku = serializers.ReadOnlyField(source="product.sku")
    warehouse_name = serializers.ReadOnlyField(source="warehouse.name")
    warehouse_code = serializers.ReadOnlyField(source="warehouse.code")
    available_quantity = serializers.IntegerField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Stock
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "warehouse",
            "warehouse_name",
            "warehouse_code",
            "quantity",
            "reserved_quantity",
            "available_quantity",
            "low_stock_threshold",
            "is_low_stock",
            "last_updated",
        ]


class StockMovementSerializer(serializers.ModelSerializer):
    """Serializer for stock movements."""

    product_name = serializers.ReadOnlyField(source="product.name")
    product_sku = serializers.ReadOnlyField(source="product.sku")
    warehouse_name = serializers.ReadOnlyField(source="warehouse.name")
    warehouse_code = serializers.ReadOnlyField(source="warehouse.code")
    movement_type_display = serializers.CharField(
        source="get_movement_type_display",
        read_only=True,
    )
    created_by_name = serializers.ReadOnlyField(source="created_by.full_name")

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "warehouse",
            "warehouse_name",
            "warehouse_code",
            "movement_type",
            "movement_type_display",
            "quantity",
            "reference_id",
            "reason",
            "before_quantity",
            "after_quantity",
            "created_by",
            "created_by_name",
            "created_at",
            "notes",
        ]
        read_only_fields = [
            "id",
            "before_quantity",
            "after_quantity",
            "created_by",
            "created_by_name",
            "created_at",
        ]

    def validate(self, attrs):
        movement_type = attrs.get(
            "movement_type",
            getattr(self.instance, "movement_type", None),
        )
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", None))

        if quantity == 0:
            raise serializers.ValidationError(
                {"quantity": "Quantity cannot be zero."}
            )

        increase_types = {
            StockMovement.MovementType.PURCHASE,
            StockMovement.MovementType.RETURN,
            StockMovement.MovementType.TRANSFER_IN,
        }

        decrease_types = {
            StockMovement.MovementType.SALE,
            StockMovement.MovementType.TRANSFER_OUT,
            StockMovement.MovementType.DAMAGED,
        }

        if movement_type in increase_types and quantity < 0:
            raise serializers.ValidationError(
                {"quantity": "This movement type must have a positive quantity."}
            )

        if movement_type in decrease_types and quantity > 0:
            raise serializers.ValidationError(
                {"quantity": "This movement type must have a negative quantity."}
            )

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")

        if request and request.user and request.user.is_authenticated:
            validated_data["created_by"] = request.user

        return super().create(validated_data)


class StockMovementListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for stock movement history."""

    product_name = serializers.ReadOnlyField(source="product.name")
    warehouse_name = serializers.ReadOnlyField(source="warehouse.name")
    movement_type_display = serializers.CharField(
        source="get_movement_type_display",
        read_only=True,
    )
    created_by_name = serializers.ReadOnlyField(source="created_by.full_name")

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "product",
            "product_name",
            "warehouse",
            "warehouse_name",
            "movement_type",
            "movement_type_display",
            "quantity",
            "before_quantity",
            "after_quantity",
            "reference_id",
            "created_by_name",
            "created_at",
        ]


class StockTransferSerializer(serializers.ModelSerializer):
    """Serializer for stock transfers."""

    product_name = serializers.ReadOnlyField(source="product.name")
    product_sku = serializers.ReadOnlyField(source="product.sku")
    from_warehouse_name = serializers.ReadOnlyField(source="from_warehouse.name")
    from_warehouse_code = serializers.ReadOnlyField(source="from_warehouse.code")
    to_warehouse_name = serializers.ReadOnlyField(source="to_warehouse.name")
    to_warehouse_code = serializers.ReadOnlyField(source="to_warehouse.code")
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    requested_by_name = serializers.ReadOnlyField(source="requested_by.full_name")
    approved_by_name = serializers.ReadOnlyField(source="approved_by.full_name")

    class Meta:
        model = StockTransfer
        fields = [
            "id",
            "from_warehouse",
            "from_warehouse_name",
            "from_warehouse_code",
            "to_warehouse",
            "to_warehouse_name",
            "to_warehouse_code",
            "product",
            "product_name",
            "product_sku",
            "quantity",
            "status",
            "status_display",
            "tracking_number",
            "shipped_at",
            "delivered_at",
            "reason",
            "requested_by",
            "requested_by_name",
            "approved_by",
            "approved_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "shipped_at",
            "delivered_at",
            "requested_by",
            "requested_by_name",
            "approved_by",
            "approved_by_name",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        from_warehouse = attrs.get(
            "from_warehouse",
            getattr(self.instance, "from_warehouse", None),
        )
        to_warehouse = attrs.get(
            "to_warehouse",
            getattr(self.instance, "to_warehouse", None),
        )
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", None))

        if from_warehouse and to_warehouse and from_warehouse == to_warehouse:
            raise serializers.ValidationError(
                {
                    "to_warehouse": "Source and destination warehouses cannot be the same."
                }
            )

        if quantity is not None and quantity <= 0:
            raise serializers.ValidationError(
                {"quantity": "Transfer quantity must be greater than zero."}
            )

        return attrs

    def create(self, validated_data):
        request = self.context.get("request")

        if request and request.user and request.user.is_authenticated:
            validated_data["requested_by"] = request.user

        return super().create(validated_data)


class StockTransferListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for stock transfer lists."""

    product_name = serializers.ReadOnlyField(source="product.name")
    from_warehouse_name = serializers.ReadOnlyField(source="from_warehouse.name")
    to_warehouse_name = serializers.ReadOnlyField(source="to_warehouse.name")
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = StockTransfer
        fields = [
            "id",
            "product",
            "product_name",
            "from_warehouse",
            "from_warehouse_name",
            "to_warehouse",
            "to_warehouse_name",
            "quantity",
            "status",
            "status_display",
            "tracking_number",
            "created_at",
            "updated_at",
        ]


class StockReserveSerializer(serializers.Serializer):
    """Serializer for reserving stock."""

    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all())
    quantity = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        product = attrs["product"]
        warehouse = attrs["warehouse"]
        quantity = attrs["quantity"]

        try:
            stock = Stock.objects.get(product=product, warehouse=warehouse)
        except Stock.DoesNotExist:
            raise serializers.ValidationError(
                "Stock record does not exist for this product and warehouse."
            )

        if stock.available_quantity < quantity:
            raise serializers.ValidationError("Not enough available stock to reserve.")

        attrs["stock"] = stock
        return attrs


class StockReleaseReservationSerializer(serializers.Serializer):
    """Serializer for releasing reserved stock."""

    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all())
    quantity = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        product = attrs["product"]
        warehouse = attrs["warehouse"]
        quantity = attrs["quantity"]

        try:
            stock = Stock.objects.get(product=product, warehouse=warehouse)
        except Stock.DoesNotExist:
            raise serializers.ValidationError(
                "Stock record does not exist for this product and warehouse."
            )

        if stock.reserved_quantity < quantity:
            raise serializers.ValidationError(
                "Cannot release more than reserved quantity."
            )

        attrs["stock"] = stock
        return attrs


class StockTransferActionSerializer(serializers.Serializer):
    """Serializer for transfer actions like in_transit, complete, cancel."""

    tracking_number = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )