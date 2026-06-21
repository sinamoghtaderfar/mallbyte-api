from rest_framework import serializers

from apps.orders.models import Order
from apps.shipping.models import Shipment, ShipmentEvent


# ============================================================
# Shipment Event Serializer
# ============================================================

class ShipmentEventSerializer(serializers.ModelSerializer):
    """
    Shows shipment status history.

    Example:
    pending -> ready_to_ship
    ready_to_ship -> shipped
    shipped -> delivered
    """

    created_by_name = serializers.ReadOnlyField(source="created_by.full_name")

    class Meta:
        model = ShipmentEvent
        fields = [
            "id",
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
# Shipment List Serializer
# ============================================================

class ShipmentListSerializer(serializers.ModelSerializer):
    """
    Small serializer for shipment list.
    """

    order_number = serializers.ReadOnlyField(source="order.order_number")
    user_phone = serializers.ReadOnlyField(source="user.phone")

    carrier_display = serializers.CharField(
        source="get_carrier_display",
        read_only=True,
    )

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    class Meta:
        model = Shipment
        fields = [
            "id",
            "shipment_number",
            "order",
            "order_number",
            "user",
            "user_phone",
            "carrier",
            "carrier_display",
            "status",
            "status_display",
            "tracking_number",
            "shipping_cost",
            "created_at",
            "shipped_at",
            "delivered_at",
        ]
        read_only_fields = fields


# ============================================================
# Shipment Detail Serializer
# ============================================================

class ShipmentDetailSerializer(serializers.ModelSerializer):
    """
    Full shipment detail with shipment events.
    """

    order_number = serializers.ReadOnlyField(source="order.order_number")
    user_phone = serializers.ReadOnlyField(source="user.phone")
    user_full_name = serializers.ReadOnlyField(source="user.full_name")

    carrier_display = serializers.CharField(
        source="get_carrier_display",
        read_only=True,
    )

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    events = ShipmentEventSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id",
            "shipment_number",
            "order",
            "order_number",
            "user",
            "user_phone",
            "user_full_name",
            "carrier",
            "carrier_display",
            "status",
            "status_display",
            "tracking_number",
            "tracking_url",
            "shipping_cost",
            "receiver_name",
            "receiver_phone",
            "province",
            "city",
            "address",
            "postal_code",
            "notes",
            "shipped_at",
            "delivered_at",
            "cancelled_at",
            "created_by",
            "created_at",
            "updated_at",
            "events",
        ]
        read_only_fields = fields


# ============================================================
# Shipment Create Serializer
# ============================================================

class ShipmentCreateSerializer(serializers.Serializer):
    """
    Creates shipment from a paid order.

    Input:
    {
        "order": 1,
        "carrier": "dhl"
    }
    """

    order = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.all(),
    )

    carrier = serializers.ChoiceField(
        choices=Shipment.CarrierChoices.choices,
        required=False,
        default=Shipment.CarrierChoices.POST,
    )

    def validate_order(self, order):
        """
        Shipment can be created only for paid orders.
        """

        request = self.context["request"]
        user = request.user

        # Normal users cannot create shipments for other users.
        # Later, admin/order-manager permissions can be added here.
        if not (user.is_staff or user.is_superuser):
            raise serializers.ValidationError(
                "Only staff users can create shipments."
            )

        if order.status != Order.StatusChoices.PAID:
            raise serializers.ValidationError(
                "Shipment can be created only for paid orders."
            )

        existing_active_shipment = order.shipments.exclude(
            status__in=[
                Shipment.StatusChoices.CANCELLED,
                Shipment.StatusChoices.RETURNED,
            ]
        ).exists()

        if existing_active_shipment:
            raise serializers.ValidationError(
                "This order already has an active shipment."
            )

        return order

    def create(self, validated_data):
        """
        Create shipment using model helper.
        """

        request = self.context["request"]

        order = validated_data["order"]
        carrier = validated_data.get("carrier", Shipment.CarrierChoices.POST)

        shipment = Shipment.create_from_order(
            order=order,
            carrier=carrier,
            created_by=request.user,
        )

        return shipment


# ============================================================
# Mark Ready Serializer
# ============================================================

class ShipmentMarkReadySerializer(serializers.Serializer):
    """
    Mark shipment as ready to ship.

    Input:
    {
        "note": "Package prepared"
    }
    """

    note = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        shipment = self.context["shipment"]

        if shipment.status != Shipment.StatusChoices.PENDING:
            raise serializers.ValidationError(
                "Only pending shipments can be marked as ready."
            )

        return attrs


# ============================================================
# Mark Shipped Serializer
# ============================================================

class ShipmentMarkShippedSerializer(serializers.Serializer):
    """
    Mark shipment as shipped.

    Input:
    {
        "tracking_number": "DHL123456",
        "tracking_url": "https://...",
        "note": "Handed to carrier"
    }
    """

    tracking_number = serializers.CharField(
        max_length=120,
        required=False,
        allow_blank=True,
    )

    tracking_url = serializers.URLField(
        required=False,
        allow_blank=True,
    )

    note = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        shipment = self.context["shipment"]

        allowed_statuses = [
            Shipment.StatusChoices.PENDING,
            Shipment.StatusChoices.READY_TO_SHIP,
        ]

        if shipment.status not in allowed_statuses:
            raise serializers.ValidationError(
                "Shipment cannot be marked as shipped from this status."
            )

        return attrs


# ============================================================
# Mark Delivered Serializer
# ============================================================

class ShipmentMarkDeliveredSerializer(serializers.Serializer):
    """
    Mark shipment as delivered.

    Input:
    {
        "note": "Delivered to customer"
    }
    """

    note = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        shipment = self.context["shipment"]

        allowed_statuses = [
            Shipment.StatusChoices.SHIPPED,
            Shipment.StatusChoices.IN_TRANSIT,
            Shipment.StatusChoices.OUT_FOR_DELIVERY,
        ]

        if shipment.status not in allowed_statuses:
            raise serializers.ValidationError(
                "Shipment cannot be marked as delivered from this status."
            )

        return attrs


# ============================================================
# Shipment Cancel Serializer
# ============================================================

class ShipmentCancelSerializer(serializers.Serializer):
    """
    Cancel shipment.

    Input:
    {
        "note": "Customer requested cancellation"
    }
    """

    note = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        shipment = self.context["shipment"]

        if shipment.status == Shipment.StatusChoices.DELIVERED:
            raise serializers.ValidationError(
                "Delivered shipment cannot be cancelled."
            )

        if shipment.status == Shipment.StatusChoices.CANCELLED:
            raise serializers.ValidationError(
                "Shipment is already cancelled."
            )

        return attrs