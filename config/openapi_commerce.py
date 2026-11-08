"""Schema-only replacements for custom cart, product, CMS and health endpoints.

These classes are discovered only by drf-spectacular. Runtime URL callbacks and
business serializers remain unchanged.
"""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
    extend_schema_serializer,
)
from rest_framework import serializers

from apps.content.serializers import (
    AnnouncementSerializer,
    BannerSerializer,
    ContentPageSerializer,
    FAQItemSerializer,
)
from apps.discounts.serializers import DiscountValidateSerializer, DiscountValidationResultSerializer
from apps.observability.serializers import SystemHealthSnapshotSerializer
from apps.orders.models import Order
from apps.orders.serializers import AddToCartSerializer, CartSerializer, UpdateCartItemSerializer
from apps.products.models import ProductImage, ProductVariant, Wishlist
from apps.returns.models import ReturnRequest
from apps.support.models import SupportTicket


class CartMessageResponse(serializers.Serializer):
    message = serializers.CharField()


@extend_schema_serializer(many=False)
class CurrentCartResponse(CartSerializer):
    """The cart list action returns one current cart, not an array of carts."""


class CartViewSchema(OpenApiViewExtension):
    target_class = "apps.orders.views.CartViewSet"

    def view_replacement(self):
        item_id = OpenApiParameter("item_id", OpenApiTypes.INT, OpenApiParameter.PATH, required=True)

        class Documented(self.target):
            serializer_class = CurrentCartResponse

            @extend_schema(responses={200: CurrentCartResponse})
            def list(self, request):
                pass

            @extend_schema(request=AddToCartSerializer, responses={200: CurrentCartResponse})
            def add_item(self, request):
                pass

            @extend_schema(methods=["PATCH"], request=UpdateCartItemSerializer,
                           parameters=[item_id], responses={200: CurrentCartResponse})
            @extend_schema(methods=["DELETE"], request=None,
                           parameters=[item_id], responses={200: CurrentCartResponse})
            def item_detail(self, request, item_id=None):
                pass

            @extend_schema(request=None, responses={200: CartMessageResponse})
            def clear_cart(self, request):
                pass

        return Documented


class ProductOperationError(serializers.Serializer):
    error = serializers.CharField()


class ProductExportSchema(OpenApiViewExtension):
    target_class = "apps.products.views.ProductExportView"

    def view_replacement(self):
        class Documented(self.target):
            @extend_schema(
                parameters=[OpenApiParameter("export_format", OpenApiTypes.STR, enum=["csv", "excel"], default="csv")],
                responses={
                    (200, "text/csv"): OpenApiTypes.BINARY,
                    (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiTypes.BINARY,
                    400: ProductOperationError,
                },
            )
            def get(self, request):
                pass

        return Documented


@extend_schema_field(OpenApiTypes.BINARY)
class ProductImportFileField(serializers.FileField):
    pass


class ProductImportRequest(serializers.Serializer):
    file = ProductImportFileField(help_text="CSV or XLSX file; at most 8 MB and 1000 product rows.")


class ProductImportRowError(serializers.Serializer):
    row = serializers.IntegerField(help_text="One-based spreadsheet row, including its header row.")
    error = serializers.JSONField(help_text="DRF validation detail: field names with validation-message lists or nested details.")


class ProductImportResponse(serializers.Serializer):
    created = serializers.IntegerField(min_value=0)
    errors = ProductImportRowError(many=True)


class ProductImportSchema(OpenApiViewExtension):
    target_class = "apps.products.views.BulkProductUploadView"

    def view_replacement(self):
        class Documented(self.target):
            @extend_schema(request={"multipart/form-data": ProductImportRequest},
                           responses={201: ProductImportResponse, 400: ProductOperationError})
            def post(self, request):
                pass

        return Documented


class ComparedProduct(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    price = serializers.DecimalField(max_digits=12, decimal_places=0, coerce_to_string=False)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=0, coerce_to_string=False)
    stock = serializers.IntegerField()
    image = serializers.CharField(allow_null=True)
    attributes = serializers.DictField(child=serializers.CharField())


class ProductComparisonResponse(serializers.Serializer):
    products = ComparedProduct(many=True)
    attributes = serializers.DictField(child=serializers.CharField())


class ProductComparisonSchema(OpenApiViewExtension):
    target_class = "apps.products.views.ProductComparisonView"

    def view_replacement(self):
        class Documented(self.target):
            @extend_schema(
                parameters=[OpenApiParameter("ids", OpenApiTypes.STR, required=True,
                                             description="Comma-separated distinct positive product IDs; at most 20.")],
                responses={200: ProductComparisonResponse, 400: ProductOperationError, 404: ProductOperationError},
            )
            def get(self, request):
                pass

        return Documented


class ProductQRCodeSchema(OpenApiViewExtension):
    target_class = "apps.products.views.ProductQRCodeView"

    def view_replacement(self):
        class Documented(self.target):
            @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY, 404: ProductOperationError})
            def get(self, request, product_id):
                pass

        return Documented


class ProductLabelResponse(serializers.Serializer):
    value = serializers.CharField()
    display = serializers.CharField()
    icon = serializers.CharField()


class ProductLabelsSchema(OpenApiViewExtension):
    target_class = "apps.products.views.ProductLabelsView"

    def view_replacement(self):
        class Documented(self.target):
            # This custom GET returns a plain array, not GenericAPIView's default
            # paginated list envelope.
            pagination_class = None

            @extend_schema(responses={200: ProductLabelResponse(many=True)})
            def get(self, request):
                pass

        return Documented


class HomepageContentResponse(serializers.Serializer):
    banners = BannerSerializer(many=True)
    announcements = AnnouncementSerializer(many=True)
    featured_pages = ContentPageSerializer(many=True)
    featured_faqs = FAQItemSerializer(many=True)


class HomepageContentSchema(OpenApiViewExtension):
    target_class = "apps.content.views.HomepageContentView"

    def view_replacement(self):
        class Documented(self.target):
            @extend_schema(responses={200: HomepageContentResponse})
            def get(self, request):
                pass

        return Documented


class DiscountValidationError(serializers.Serializer):
    detail = serializers.CharField()


class DiscountValidationSchema(OpenApiViewExtension):
    target_class = "apps.discounts.views.ValidateDiscountView"

    def view_replacement(self):
        class Documented(self.target):
            @extend_schema(request=DiscountValidateSerializer,
                           responses={200: DiscountValidationResultSerializer, 400: DiscountValidationError,
                                      404: DiscountValidationError})
            def post(self, request):
                pass

        return Documented


class ObservabilityHealthResponse(SystemHealthSnapshotSerializer):
    is_stale = serializers.BooleanField(read_only=True)
    stale_after_seconds = serializers.IntegerField(read_only=True)

    class Meta(SystemHealthSnapshotSerializer.Meta):
        fields = [*SystemHealthSnapshotSerializer.Meta.fields, "is_stale", "stale_after_seconds"]
        read_only_fields = fields


class ObservabilityHealthUnavailable(serializers.Serializer):
    status = serializers.ChoiceField(choices=["unknown"])
    detail = serializers.CharField()


class ObservabilityHealthSchema(OpenApiViewExtension):
    target_class = "apps.observability.views.ObservabilityHealthView"

    def view_replacement(self):
        class Documented(self.target):
            @extend_schema(responses={200: ObservabilityHealthResponse, 503: ObservabilityHealthUnavailable})
            def get(self, request):
                pass

        return Documented


class MetricStatusCount(serializers.Serializer):
    status_code = serializers.IntegerField()
    count = serializers.IntegerField()


class MetricPathCount(serializers.Serializer):
    path = serializers.CharField()
    count = serializers.IntegerField()


class MetricSeverityCount(serializers.Serializer):
    severity = serializers.CharField()
    count = serializers.IntegerField()


class MetricTrendBucket(serializers.Serializer):
    bucket = serializers.DateTimeField()
    requests = serializers.IntegerField()
    average_ms = serializers.FloatField()


class ObservabilityMetricsResponse(serializers.Serializer):
    window = serializers.CharField(help_text="Legacy 24h value is last_24_hours; otherwise equals window_key.")
    window_key = serializers.ChoiceField(choices=["1h", "6h", "24h", "7d"])
    requests_count = serializers.IntegerField()
    error_logs_count = serializers.IntegerField()
    open_alerts_count = serializers.IntegerField()
    slow_requests_count = serializers.IntegerField()
    average_duration_ms = serializers.FloatField()
    p95_duration_ms = serializers.FloatField()
    error_rate_percent = serializers.FloatField()
    status_codes = MetricStatusCount(many=True)
    top_paths = MetricPathCount(many=True)
    open_alerts_by_severity = MetricSeverityCount(many=True)
    request_trend = MetricTrendBucket(many=True)


class MetricsWindowError(serializers.Serializer):
    window = serializers.CharField()


class ObservabilityMetricsSchema(OpenApiViewExtension):
    target_class = "apps.observability.views.ObservabilityStatsView"

    def view_replacement(self):
        class Documented(self.target):
            @extend_schema(parameters=[OpenApiParameter("window", OpenApiTypes.STR,
                                                       enum=["1h", "6h", "24h", "7d"], default="24h")],
                           responses={200: ObservabilityMetricsResponse, 400: MetricsWindowError})
            def get(self, request):
                pass

        return Documented


class SchemaQuerysetExtension(OpenApiViewExtension):
    """Make model metadata available without evaluating user-owned querysets."""

    model = None

    def view_replacement(self):
        model = self.model

        class Documented(self.target):
            def get_queryset(self):
                if getattr(self, "swagger_fake_view", False):
                    return model.objects.none()
                return super().get_queryset()

        return Documented


class OrderQuerysetSchema(SchemaQuerysetExtension):
    target_class = "apps.orders.views.OrderViewSet"
    model = Order


class ProductImageQuerysetSchema(SchemaQuerysetExtension):
    target_class = "apps.products.views.ProductImageViewSet"
    model = ProductImage


class ProductVariantQuerysetSchema(SchemaQuerysetExtension):
    target_class = "apps.products.views.ProductVariantViewSet"
    model = ProductVariant


class WishlistQuerysetSchema(SchemaQuerysetExtension):
    target_class = "apps.products.views.WishlistViewSet"
    model = Wishlist


class ReturnRequestQuerysetSchema(SchemaQuerysetExtension):
    target_class = "apps.returns.views.ReturnRequestViewSet"
    model = ReturnRequest


class SupportTicketQuerysetSchema(SchemaQuerysetExtension):
    target_class = "apps.support.views.SupportTicketViewSet"
    model = SupportTicket
