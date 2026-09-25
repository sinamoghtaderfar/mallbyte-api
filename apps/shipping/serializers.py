"""Serializers for order-level and seller-specific shipments."""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.orders.models import Order, SellerOrderFulfillment
from apps.shipping.models import Shipment, ShipmentEvent

ACTIVE_SHIPMENT_EXCLUDED_STATUSES = (
    Shipment.StatusChoices.CANCELLED,
    Shipment.StatusChoices.RETURNED,
)


class ShipmentEventSerializer(serializers.ModelSerializer):
    """Show the history of a shipment's status changes."""

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


class EligibleShipmentOrderSerializer(serializers.ModelSerializer):
    """Paid orders with sellers who can still receive a shipment."""

    user_email = serializers.ReadOnlyField(source="user.email")
    user_full_name = serializers.ReadOnlyField(source="user.full_name")
    eligible_sellers = serializers.SerializerMethodField()
    requires_seller_selection = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "user",
            "user_email",
            "user_full_name",
            "total_amount",
            "shipping_cost",
            "receiver_name",
            "receiver_phone",
            "province",
            "city",
            "paid_at",
            "created_at",
            "eligible_sellers",
            "requires_seller_selection",
        ]
        read_only_fields = fields

    @staticmethod
    def _seller_ids(obj):
        return list(obj.items.values_list("product__seller_id", flat=True).distinct())

    def get_requires_seller_selection(self, obj):
        return len(self._seller_ids(obj)) > 1

    def get_eligible_sellers(self, obj):
        # Older orders may not contain order items. They retain the legacy
        # order-level shipment workflow and therefore have no seller selector.
        if obj.payment_status != Order.PaymentStatusChoices.PAID:
            return []

        active_shipments = Shipment.objects.filter(order=obj).exclude(
            status__in=ACTIVE_SHIPMENT_EXCLUDED_STATUSES
        )
        if active_shipments.filter(seller_fulfillment__isnull=True).exists():
            return []

        already_assigned = set(
            active_shipments.values_list("seller_fulfillment__seller_id", flat=True)
        )
        statuses = dict(
            SellerOrderFulfillment.objects.filter(order=obj).values_list(
                "seller_id", "status"
            )
        )
        sellers = {}
        for item in obj.items.select_related("product__seller"):
            seller = item.product.seller
            if seller.pk in sellers or seller.pk in already_assigned:
                continue
            fulfillment_status = statuses.get(seller.pk, Order.StatusChoices.PAID)
            if fulfillment_status not in {
                Order.StatusChoices.PAID,
                Order.StatusChoices.PROCESSING,
            }:
                continue
            sellers[seller.pk] = {
                "id": seller.pk,
                "name": seller.full_name or seller.email or str(seller.pk),
                "status": fulfillment_status,
            }
        return list(sellers.values())


class SellerShipmentFieldsMixin:
    """Seller-specific fields shared by shipment list and detail responses."""

    @staticmethod
    def _fulfillment(obj):
        return obj.seller_fulfillment

    def get_seller(self, obj):
        fulfillment = self._fulfillment(obj)
        return fulfillment.seller_id if fulfillment else None

    def get_seller_name(self, obj):
        fulfillment = self._fulfillment(obj)
        if not fulfillment:
            return None
        seller = fulfillment.seller
        return seller.full_name or seller.email or str(seller.pk)

    def get_seller_status(self, obj):
        fulfillment = self._fulfillment(obj)
        return fulfillment.status if fulfillment else None


class ShipmentListSerializer(SellerShipmentFieldsMixin, serializers.ModelSerializer):
    """Small shipment serializer for the shipment list."""

    seller = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    seller_status = serializers.SerializerMethodField()
    order_number = serializers.ReadOnlyField(source="order.order_number")
    user_email = serializers.ReadOnlyField(source="user.email")
    carrier_display = serializers.CharField(
        source="get_carrier_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id",
            "shipment_number",
            "order",
            "order_number",
            "user",
            "user_email",
            "seller_fulfillment",
            "seller",
            "seller_name",
            "seller_status",
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


class ShipmentDetailSerializer(SellerShipmentFieldsMixin, serializers.ModelSerializer):
    """Full shipment detail including seller and shipment events."""

    seller = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    seller_status = serializers.SerializerMethodField()
    order_number = serializers.ReadOnlyField(source="order.order_number")
    user_email = serializers.ReadOnlyField(source="user.email")
    user_full_name = serializers.ReadOnlyField(source="user.full_name")
    carrier_display = serializers.CharField(
        source="get_carrier_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    events = ShipmentEventSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id",
            "shipment_number",
            "order",
            "order_number",
            "user",
            "user_email",
            "user_full_name",
            "seller_fulfillment",
            "seller",
            "seller_name",
            "seller_status",
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


class ShipmentCreateSerializer(serializers.Serializer):
    """Create a shipment for one seller (or a legacy order without items).

    Single-seller input: {"order": 1, "carrier": "dhl"}
    Multi-seller input:  {"order": 1, "seller": 5, "carrier": "dhl"}
    """

    order = serializers.PrimaryKeyRelatedField(queryset=Order.objects.all())
    seller = serializers.IntegerField(min_value=1, required=False)
    carrier = serializers.ChoiceField(
        choices=Shipment.CarrierChoices.choices,
        required=False,
        default=Shipment.CarrierChoices.POST,
    )

    def validate_order(self, order):
        user = self.context["request"].user
        if not (user.is_staff or user.is_superuser):
            raise serializers.ValidationError("Only staff users can create shipments.")
        if (
            order.status
            not in {
                Order.StatusChoices.PAID,
                Order.StatusChoices.PROCESSING,
            }
            or order.payment_status != Order.PaymentStatusChoices.PAID
        ):
            raise serializers.ValidationError("Shipment requires a paid order.")
        return order

    def validate(self, attrs):
        order = attrs["order"]
        seller_id = attrs.get("seller")
        seller_ids = set(
            order.items.values_list("product__seller_id", flat=True).distinct()
        )
        active_shipments = Shipment.objects.filter(order=order).exclude(
            status__in=ACTIVE_SHIPMENT_EXCLUDED_STATUSES
        )

        # A legacy, order-wide shipment cannot coexist with seller shipments.
        if active_shipments.filter(seller_fulfillment__isnull=True).exists():
            raise serializers.ValidationError(
                {"order": "This order already has an active shipment."}
            )

        if not seller_ids:
            if seller_id is not None:
                raise serializers.ValidationError(
                    {"seller": "This order has no seller items."}
                )
            if active_shipments.exists():
                raise serializers.ValidationError(
                    {"order": "This order already has an active shipment."}
                )
            return attrs

        if seller_id is None:
            if len(seller_ids) > 1:
                raise serializers.ValidationError(
                    {"seller": "Choose a seller for this multi-seller order."}
                )
            seller_id = next(iter(seller_ids))
            attrs["seller"] = seller_id
        elif seller_id not in seller_ids:
            raise serializers.ValidationError(
                {"seller": "This seller has no items in the order."}
            )

        if active_shipments.filter(seller_fulfillment__seller_id=seller_id).exists():
            raise serializers.ValidationError(
                {"seller": "This seller already has an active shipment."}
            )

        seller_status = (
            SellerOrderFulfillment.objects.filter(order=order, seller_id=seller_id)
            .values_list("status", flat=True)
            .first()
        )
        if seller_status is not None and seller_status not in {
            Order.StatusChoices.PAID,
            Order.StatusChoices.PROCESSING,
        }:
            raise serializers.ValidationError(
                {"seller": "This seller's order cannot enter shipping."}
            )
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        try:
            return Shipment.create_from_order(
                order=validated_data["order"],
                seller=validated_data.get("seller"),
                carrier=validated_data.get("carrier", Shipment.CarrierChoices.POST),
                created_by=request.user,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)}
            ) from exc


class ShipmentMarkReadySerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        shipment = self.context["shipment"]
        if shipment.status != Shipment.StatusChoices.PENDING:
            raise serializers.ValidationError(
                "Only pending shipments can be marked as ready."
            )
        return attrs


class ShipmentMarkShippedSerializer(serializers.Serializer):
    tracking_number = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    tracking_url = serializers.URLField(required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        shipment = self.context["shipment"]
        if shipment.status not in {
            Shipment.StatusChoices.PENDING,
            Shipment.StatusChoices.READY_TO_SHIP,
        }:
            raise serializers.ValidationError(
                "Shipment cannot be marked as shipped from this status."
            )
        return attrs


class ShipmentMarkDeliveredSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        shipment = self.context["shipment"]
        if shipment.status not in {
            Shipment.StatusChoices.SHIPPED,
            Shipment.StatusChoices.IN_TRANSIT,
            Shipment.StatusChoices.OUT_FOR_DELIVERY,
        }:
            raise serializers.ValidationError(
                "Shipment cannot be delivered from this status."
            )
        return attrs


class ShipmentCancelSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        shipment = self.context["shipment"]
        if shipment.status in {
            Shipment.StatusChoices.DELIVERED,
            Shipment.StatusChoices.CANCELLED,
        }:
            raise serializers.ValidationError(
                "Delivered or already cancelled shipments cannot be cancelled."
            )
        return attrs
