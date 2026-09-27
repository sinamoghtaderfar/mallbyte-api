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


# Seller responses are intentionally allowlisted. Never reuse the admin
# serializer or load unfiltered return items for the seller endpoints.
class PublicReturnItemSerializer(ReturnItemSerializer):
    class Meta(ReturnItemSerializer.Meta):
        fields = [
            field for field in ReturnItemSerializer.Meta.fields
            if field != "inspection_note"
        ]


class PublicReturnHistorySerializer(serializers.ModelSerializer):
    # Admin notes in status history may include private review information.
    # Preserve the JSON shape consumed by existing customer/seller components.
    changed_by = serializers.SerializerMethodField()
    note = serializers.SerializerMethodField()

    @staticmethod
    def get_changed_by(obj):
        return None

    @staticmethod
    def get_note(obj):
        return ""

    class Meta:
        model = ReturnStatusHistory
        fields = [
            "id", "old_status", "new_status", "changed_by", "note",
            "created_at", "updated_at",
        ]


class CustomerReturnRequestDetailSerializer(ReturnRequestDetailSerializer):
    items = PublicReturnItemSerializer(many=True, read_only=True)
    status_history = PublicReturnHistorySerializer(many=True, read_only=True)
    attachments = serializers.SerializerMethodField()

    def get_attachments(self, obj):
        # Admin-only uploads are not automatically visible to the customer.
        own_uploads = [
            attachment for attachment in obj.attachments.all()
            if attachment.uploaded_by_id == obj.customer_id
        ]
        return ReturnAttachmentSerializer(
            own_uploads, many=True, context=self.context
        ).data

    class Meta(ReturnRequestDetailSerializer.Meta):
        fields = [
            field for field in ReturnRequestDetailSerializer.Meta.fields
            if field != "internal_note"
        ]


class SellerVisibleReturnMixin:
    """Calculate money exclusively from the items prefetched for this seller."""

    @staticmethod
    def visible_items(obj):
        # Fail closed: missing seller-specific prefetch must not load all items.
        return getattr(obj, "seller_visible_items", ())

    def get_reason(self, obj):
        items = self.visible_items(obj)
        return items[0].reason if items else None

    def get_total_requested_amount(self, obj):
        from decimal import Decimal
        amount = sum(
            (item.requested_refund_amount for item in self.visible_items(obj)),
            Decimal("0.00"),
        )
        return f"{amount:.2f}"

    def get_total_approved_amount(self, obj):
        from decimal import Decimal
        amount = sum(
            (item.approved_refund_amount for item in self.visible_items(obj)),
            Decimal("0.00"),
        )
        return f"{amount:.2f}"


class SellerReturnRequestListSerializer(
    SellerVisibleReturnMixin, serializers.ModelSerializer
):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer = serializers.StringRelatedField(read_only=True)
    reason = serializers.SerializerMethodField()
    total_requested_amount = serializers.SerializerMethodField()
    total_approved_amount = serializers.SerializerMethodField()

    class Meta:
        model = ReturnRequest
        fields = [
            "id", "request_number", "customer", "order", "order_number",
            "status", "reason", "requested_resolution", "refund_method",
            "total_requested_amount", "total_approved_amount",
            "created_at", "updated_at",
        ]


class SellerReturnItemSerializer(PublicReturnItemSerializer):
    """Whitelist own-item fields; do not expose internal inspection notes."""


class SellerReturnAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnAttachment
        fields = [
            "id", "return_item", "attachment_type", "file", "caption",
            "created_at", "updated_at",
        ]


class SellerReturnRequestDetailSerializer(SellerReturnRequestListSerializer):
    items = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    status_history = PublicReturnHistorySerializer(many=True, read_only=True)
    reviewed_by = serializers.StringRelatedField(read_only=True)
    customer_note = serializers.SerializerMethodField()

    @staticmethod
    def get_customer_note(obj):
        # The request-wide note may discuss another seller's products.
        # Each seller can see the customer_note on their own return items.
        return ""

    def get_items(self, obj):
        return SellerReturnItemSerializer(
            self.visible_items(obj), many=True, context=self.context
        ).data

    def get_attachments(self, obj):
        # Unlinked (request-wide) and other-seller attachments are hidden.
        return SellerReturnAttachmentSerializer(
            getattr(obj, "seller_visible_attachments", ()),
            many=True,
            context=self.context,
        ).data

    class Meta(SellerReturnRequestListSerializer.Meta):
        fields = SellerReturnRequestListSerializer.Meta.fields + [
            "customer_note", "reviewed_by", "reviewed_at", "closed_at",
            "items", "attachments", "status_history",
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
