from rest_framework import serializers

from apps.orders.models import Order, OrderItem
from apps.returns.models import (
    ReturnAttachment,
    ReturnItem,
    ReturnRequest,
    ReturnShipment,
    ReturnStatusHistory,
)
from apps.returns.services import create_return_request


class ReturnItemCreateSerializer(serializers.Serializer):
    order_item = serializers.PrimaryKeyRelatedField(
        queryset=OrderItem.objects.select_related("order", "product").all()
    )
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.ChoiceField(
        choices=ReturnRequest.Reason.choices,
        required=False,
    )
    condition = serializers.ChoiceField(
        choices=ReturnItem.ItemCondition.choices,
        required=False,
    )
    customer_note = serializers.CharField(
        required=False,
        allow_blank=True,
    )


class ReturnRequestCreateSerializer(serializers.Serializer):
    order = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.prefetch_related("items").all()
    )
    reason = serializers.ChoiceField(
        choices=ReturnRequest.Reason.choices,
        default=ReturnRequest.Reason.OTHER,
    )
    requested_resolution = serializers.ChoiceField(
        choices=ReturnRequest.RequestedResolution.choices,
        default=ReturnRequest.RequestedResolution.REFUND,
    )
    refund_method = serializers.ChoiceField(
        choices=ReturnRequest.RefundMethod.choices,
        default=ReturnRequest.RefundMethod.ORIGINAL_PAYMENT,
    )
    customer_note = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    items = ReturnItemCreateSerializer(many=True)

    def create(self, validated_data):
        request = self.context["request"]

        return create_return_request(
            customer=request.user,
            order=validated_data["order"],
            items=validated_data["items"],
            reason=validated_data["reason"],
            requested_resolution=validated_data["requested_resolution"],
            refund_method=validated_data["refund_method"],
            customer_note=validated_data.get("customer_note", ""),
        )


class ReturnItemSerializer(serializers.ModelSerializer):
    order_item_id = serializers.IntegerField(source="order_item.id", read_only=True)
    product_name = serializers.CharField(
        source="order_item.product_name", read_only=True
    )
    product_sku = serializers.CharField(source="order_item.product_sku", read_only=True)
    unit_price = serializers.DecimalField(
        source="order_item.unit_price",
        max_digits=12,
        decimal_places=0,
        read_only=True,
    )

    class Meta:
        model = ReturnItem
        fields = [
            "id",
            "order_item_id",
            "product_name",
            "product_sku",
            "unit_price",
            "quantity",
            "reason",
            "condition",
            "status",
            "customer_note",
            "inspection_note",
            "requested_refund_amount",
            "approved_refund_amount",
            "created_at",
            "updated_at",
        ]


class ReturnAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = ReturnAttachment
        fields = [
            "id",
            "return_item",
            "uploaded_by",
            "attachment_type",
            "file",
            "caption",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uploaded_by",
            "created_at",
            "updated_at",
        ]


class ReturnShipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnShipment
        fields = [
            "id",
            "carrier",
            "tracking_number",
            "tracking_url",
            "shipping_label",
            "shipped_at",
            "received_at",
            "created_at",
            "updated_at",
        ]


class ReturnStatusHistorySerializer(serializers.ModelSerializer):
    changed_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = ReturnStatusHistory
        fields = [
            "id",
            "old_status",
            "new_status",
            "changed_by",
            "note",
            "created_at",
            "updated_at",
        ]


class ReturnRequestListSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = ReturnRequest
        fields = [
            "id",
            "request_number",
            "customer",
            "order",
            "order_number",
            "status",
            "reason",
            "requested_resolution",
            "refund_method",
            "total_requested_amount",
            "total_approved_amount",
            "created_at",
            "updated_at",
        ]


class ReturnRequestDetailSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer = serializers.StringRelatedField(read_only=True)
    reviewed_by = serializers.StringRelatedField(read_only=True)
    items = ReturnItemSerializer(many=True, read_only=True)
    attachments = ReturnAttachmentSerializer(many=True, read_only=True)
    shipment = ReturnShipmentSerializer(read_only=True)
    status_history = ReturnStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = ReturnRequest
        fields = [
            "id",
            "request_number",
            "customer",
            "order",
            "order_number",
            "status",
            "reason",
            "requested_resolution",
            "refund_method",
            "customer_note",
            "internal_note",
            "total_requested_amount",
            "total_approved_amount",
            "reviewed_by",
            "reviewed_at",
            "closed_at",
            "items",
            "attachments",
            "shipment",
            "status_history",
            "created_at",
            "updated_at",
        ]


class ReturnActionSerializer(serializers.Serializer):
    note = serializers.CharField(
        required=False,
        allow_blank=True,
    )


class ReturnApproveSerializer(serializers.Serializer):
    note = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    approved_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        min_value=0,
    )
