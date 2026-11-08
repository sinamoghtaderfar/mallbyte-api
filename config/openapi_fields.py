"""Schema-only types for computed serializer output; no runtime serializers change."""
from drf_spectacular.extensions import OpenApiSerializerExtension
from rest_framework import serializers


def _document_fields(target, factory):
    class Contract(OpenApiSerializerExtension):
        target_class = target
        match_subclasses = True

        def map_serializer(self, auto_schema, direction):
            fields = {name: field for name, field in factory(self.target).items() if name in self.target.fields}
            documented = type(f"{type(self.target).__name__}OpenAPI", (type(self.target),), fields)
            return auto_schema._map_serializer(documented(context=self.target.context), direction, bypass_extensions=True)


def _text(*, nullable=False, **kwargs):
    # API file links may be relative paths, so these deliberately are not URI format.
    return serializers.CharField(read_only=True, allow_null=nullable, **kwargs)


def _integer(*, nullable=False):
    return serializers.IntegerField(read_only=True, allow_null=nullable)


def _number():
    # SerializerMethodField/ReadOnlyField Decimals reach JSONEncoder as numbers.
    return serializers.FloatField(read_only=True)


def _money_string():
    return serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)


class ProductAttributeOutput(serializers.Serializer):
    attribute = serializers.CharField()
    attribute_slug = serializers.CharField()
    value = serializers.CharField()
    value_slug = serializers.CharField()


class EligibleSellerOutput(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.CharField()


class ConsoleRoleOutput(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


_document_fields("apps.analytics.serializers.AnalyticsGeneratedReportSerializer", lambda target: {"file_url": _text(nullable=True), "file": _text(nullable=True)})
for _name in ("ContentPageSerializer", "BannerSerializer", "AnnouncementSerializer"):
    _document_fields(f"apps.content.serializers.{_name}", lambda target: {"is_visible": serializers.BooleanField(read_only=True)})


def _faq(target):
    from apps.content.serializers import FAQItemSerializer
    return {"items": FAQItemSerializer(many=True, read_only=True)}


def _navigation_item(target):
    return {"children": type(target)(many=True, read_only=True, help_text="The API supports two levels; child items are leaves.")}


def _navigation_menu(target):
    from apps.content.serializers import NavigationItemSerializer
    return {"items": NavigationItemSerializer(many=True, read_only=True)}


_document_fields("apps.content.serializers.FAQCategorySerializer", _faq)
_document_fields("apps.content.serializers.NavigationItemSerializer", _navigation_item)
_document_fields("apps.content.serializers.NavigationMenuSerializer", _navigation_menu)

for _name, _fields in (
    ("RequestLogSerializer", ("user_display",)),
    ("ErrorLogSerializer", ("user_display", "resolved_by_display")),
    ("AuditLogSerializer", ("actor_display",)),
    ("ObservabilityAlertSerializer", ("acknowledged_by_display", "resolved_by_display")),
):
    _document_fields(f"apps.observability.serializers.{_name}", lambda target, names=_fields: {name: _text(nullable=True) for name in names})
_document_fields("apps.observability.workflow_serializers.RequestSummarySerializer", lambda target: {
    "is_error": serializers.BooleanField(read_only=True), "is_slow": serializers.BooleanField(read_only=True),
})

_document_fields("apps.products.serializers.CategorySerializer", lambda target: {"children": type(target)(many=True, read_only=True)})
_document_fields("apps.products.serializers.ProductVariantSerializer", lambda target: {"final_price": _number()})
_document_fields("apps.products.serializers.ProductListSerializer", lambda target: {
    "final_price": _number(), "label_display": serializers.ListField(child=_text(), read_only=True),
    "stock": _integer(), "reserved_stock": _integer(), "available_stock": _integer(), "main_image": _text(nullable=True),
})
_document_fields("apps.products.serializers.ProductDetailSerializer", lambda target: {
    "final_price": _number(), "brand_logo": _text(nullable=True),
    "label_display": serializers.ListField(child=_text(), read_only=True),
    "stock": _integer(), "reserved_stock": _integer(), "available_stock": _integer(),
    "attributes": ProductAttributeOutput(many=True, read_only=True), "average_rating": _number(), "reviews_count": _integer(),
})
for _name in ("WishlistSerializer", "RecentlyViewedSerializer"):
    _document_fields(f"apps.products.serializers.{_name}", lambda target: {"product_image": _text(nullable=True)})

_document_fields("apps.orders.serializers.CartItemSerializer", lambda target: {"available_stock": _integer(), "product_price": _number()})
_document_fields("apps.orders.serializers.CartSerializer", lambda target: {"subtotal": _text()})
_document_fields("apps.orders.serializers.OrderListSerializer", lambda target: {"items_count": _integer()})


def _seller_order(target):
    from apps.orders.serializers import SellerOrderItemSerializer
    return {
        "seller_items_count": _integer(), "seller_total_amount": _number(),
        "seller_status": _text(), "seller_status_display": _text(),
        "items": SellerOrderItemSerializer(many=True, read_only=True),
    }


for _name in ("SellerOrderListSerializer", "SellerOrderDetailSerializer"):
    _document_fields(f"apps.orders.serializers.{_name}", _seller_order)

_document_fields("apps.rbac.serializers.RoleSerializer", lambda target: {
    "permissions": serializers.ListField(child=_text(), read_only=True), "permissions_count": _integer(),
})
_document_fields("apps.rbac.serializers.UserRoleSerializer", lambda target: {"assigned_by_name": _text(nullable=True), "is_expired": serializers.BooleanField(read_only=True)})
_document_fields("apps.rbac.serializers.AdminLogSerializer", lambda target: {"admin_name": _text(nullable=True), "target_user_name": _text(nullable=True)})
_document_fields("apps.rbac.super_admin.ConsoleUserSerializer", lambda target: {"roles": ConsoleRoleOutput(many=True, read_only=True)})


def _seller_return(target):
    from apps.returns.serializers import SellerReturnAttachmentSerializer, SellerReturnItemSerializer
    return {
        "reason": _text(nullable=True), "total_requested_amount": _money_string(), "total_approved_amount": _money_string(),
        "customer_note": _text(), "items": SellerReturnItemSerializer(many=True, read_only=True),
        "attachments": SellerReturnAttachmentSerializer(many=True, read_only=True),
    }


for _name in ("SellerReturnRequestListSerializer", "SellerReturnRequestDetailSerializer"):
    _document_fields(f"apps.returns.serializers.{_name}", _seller_return)
_document_fields("apps.returns.serializers.PublicReturnHistorySerializer", lambda target: {"changed_by": _text(nullable=True), "note": _text()})
for _name in ("ReturnAttachmentSerializer", "SellerReturnAttachmentSerializer"):
    _document_fields(f"apps.returns.serializers.{_name}", lambda target: {"file": _text()})
_document_fields("apps.returns.serializers.ReturnShipmentSerializer", lambda target: {"shipping_label": _text(nullable=True)})


def _customer_return(target):
    from apps.returns.serializers import ReturnAttachmentSerializer
    return {"attachments": ReturnAttachmentSerializer(many=True, read_only=True)}


_document_fields("apps.returns.serializers.CustomerReturnRequestDetailSerializer", _customer_return)
_document_fields("apps.shipping.serializers.EligibleShipmentOrderSerializer", lambda target: {
    "requires_seller_selection": serializers.BooleanField(read_only=True), "eligible_sellers": EligibleSellerOutput(many=True, read_only=True),
})
for _name in ("ShipmentListSerializer", "ShipmentDetailSerializer"):
    _document_fields(f"apps.shipping.serializers.{_name}", lambda target: {
        "seller": _integer(nullable=True), "seller_name": _text(nullable=True), "seller_status": _text(nullable=True),
    })
_document_fields("apps.support.serializers.TicketAttachmentSerializer", lambda target: {"download_url": _text()})


def _support_ticket(target):
    from apps.support.serializers import TicketAttachmentSerializer, TicketMessageSerializer
    return {
        "messages": TicketMessageSerializer(many=True, read_only=True),
        "attachments": TicketAttachmentSerializer(many=True, read_only=True),
        "messages_truncated": serializers.BooleanField(read_only=True), "attachments_truncated": serializers.BooleanField(read_only=True),
    }


_document_fields("apps.support.serializers.SupportTicketSerializer", _support_ticket)
