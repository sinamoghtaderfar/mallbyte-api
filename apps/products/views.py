import csv
import zipfile

import pandas as pd
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import transaction
from django.db.models import F, Prefetch, Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from openpyxl import Workbook
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.products.services import create_product_notification, requeue_product_for_review
from apps.rbac.permissions import IsProductAdmin, IsVendor, user_has_active_role

from .filters import ProductFilter
from .models import (
    Attribute,
    AttributeValue,
    Brand,
    Category,
    Product,
    ProductAttribute,
    ProductImage,
    ProductVariant,
    RecentlyViewed,
    Tag,
    Wishlist,
)
from .querysets import catalog_queryset, main_image_prefetch
from .serializers import (
    AttributeSerializer,
    AttributeValueSerializer,
    BrandSerializer,
    CategorySerializer,
    ProductCreateUpdateSerializer,
    ProductDetailSerializer,
    ProductImageSerializer,
    ProductListSerializer,
    ProductVariantSerializer,
    RecentlyViewedSerializer,
    TagSerializer,
    WishlistSerializer,
    catalog_write,
)


class CatalogOrderingFilter(filters.OrderingFilter):
    """Relevance-first search unless the customer explicitly chooses a sort order."""

    def get_ordering(self, request, queryset, view):
        if request.query_params.get("search", "").strip() and not request.query_params.get("ordering"):
            return ["-_catalog_relevance", "-created_at", "-id"]
        return super().get_ordering(request, queryset, view)


# ==================== Category Views ====================


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]
        return [IsAuthenticated(), IsProductAdmin()]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action in ("list", "retrieve"):
            children = {}
            for category in Category.objects.filter(is_active=True).select_related("parent").order_by("order", "pk"):
                children.setdefault(category.parent_id, []).append(category)
            context["category_children"] = children
        return context

    def get_queryset(self):
        queryset = (Category.objects.all() if self.action not in ("list", "retrieve") else super().get_queryset()).select_related("parent")
        if self.action != "list":
            return queryset
        parent = self.request.query_params.get("parent")
        if parent == "null" or parent is None:
            queryset = queryset.filter(parent__isnull=True)
        elif parent:
            queryset = queryset.filter(parent_id=parent)
        return queryset


# ==================== Brand Views ====================


class BrandViewSet(viewsets.ModelViewSet):
    queryset = Brand.objects.filter(is_active=True)
    serializer_class = BrandSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]
        return [IsAuthenticated(), IsProductAdmin()]

    def get_queryset(self):
        return Brand.objects.all() if self.action not in ("list", "retrieve") else super().get_queryset()


# ==================== Attribute Views ====================


class AttributeViewSet(viewsets.ModelViewSet):
    """ViewSet for managing attributes"""

    queryset = Attribute.objects.all()
    serializer_class = AttributeSerializer
    permission_classes = [IsAuthenticated, IsProductAdmin]


class AttributeValueViewSet(viewsets.ModelViewSet):
    """ViewSet for managing attribute values"""

    queryset = AttributeValue.objects.all()
    serializer_class = AttributeValueSerializer
    permission_classes = [IsAuthenticated, IsProductAdmin]

    def get_queryset(self):
        queryset = super().get_queryset()
        attribute_id = self.request.query_params.get("attribute")
        if attribute_id:
            queryset = queryset.filter(attribute_id=attribute_id)
        return queryset


# ==================== Tag Views ====================


class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer

    def get_permissions(self):
        if self.action in ["list"]:
            return [AllowAny()]
        return [IsAuthenticated(), IsProductAdmin()]


# ==================== Product Views ====================
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        CatalogOrderingFilter,
    ]
    filterset_class = ProductFilter
    search_fields = ["name", "description", "sku", "brand__name"]
    ordering_fields = ["price", "created_at", "views_count"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        elif self.action in ["create", "update", "partial_update"]:
            return ProductCreateUpdateSerializer
        return ProductDetailSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]
        elif self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAuthenticated(), IsVendor()]
        elif self.action in ["approve", "reject", "feature"]:
            return [IsAuthenticated(), IsProductAdmin()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        action = getattr(self, "action", None)
        if action in ("approve", "reject", "feature"):
            queryset = queryset.select_for_update(of=("self",))
        publicly_visible = Q(
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

        # Storefront queries must not change when a customer is also a seller.
        if action == "list":
            # One aggregate query plus one image prefetch replaces per-product stock
            # and image lookups. Public visibility is always enforced first.
            queryset = catalog_queryset(queryset.filter(publicly_visible))
            search = self.request.query_params.get("search", "").strip()
            if search:
                vector = (
                    SearchVector("name", weight="A", config="simple")
                    + SearchVector("sku", weight="A", config="simple")
                    + SearchVector("brand__name", weight="B", config="simple")
                    + SearchVector("description", weight="C", config="simple")
                )
                queryset = queryset.annotate(
                    _catalog_relevance=SearchRank(vector, SearchQuery(search, search_type="websearch", config="simple"))
                )
            return queryset

        if action in ("related", "add_view", "featured"):
            return queryset.filter(publicly_visible)

        if action == "retrieve":
            # Sellers need to inspect their own drafts, but not other sellers'
            # unpublished products. Product admins can moderate all statuses.
            if user.is_authenticated:
                if user.is_superuser or user_has_active_role(user, "product_admin"):
                    return queryset
                if hasattr(user, "seller") and user.seller.is_verified:
                    return queryset.filter(publicly_visible | Q(seller=user))
            return queryset.filter(publicly_visible)

        if action in ("update", "partial_update", "destroy"):
            # An approved product from another seller must never be editable.
            return queryset.filter(seller=user)

        # Moderation actions are separately protected by IsProductAdmin.
        return queryset

    def perform_create(self, serializer):
        product = serializer.save(
            seller=self.request.user,
            status=Product.StatusChoices.PENDING,
        )

        create_product_notification(
            user=product.seller,
            product=product,
            template_key="product_submitted",
            product_name=product.name,
        )

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def approve(self, request, pk=None):
        product = self.get_object()

        product.status = Product.StatusChoices.APPROVED
        product.approved_by = request.user
        product.approved_at = timezone.now()
        product.save()

        create_product_notification(
            user=product.seller,
            product=product,
            template_key="product_approved",
            product_name=product.name,
        )

        return Response({"message": "Product approved successfully"})

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reject(self, request, pk=None):
        product = self.get_object()
        reason = request.data.get("reason", "No reason provided")

        product.status = Product.StatusChoices.REJECTED
        product.approved_by = None
        product.approved_at = None
        product.save()

        create_product_notification(
            user=product.seller,
            product=product,
            template_key="product_rejected",
            product_name=product.name,
            reason=reason,
            metadata={
                "reason": reason,
            },
        )

        return Response({"message": f"Product rejected. Reason: {reason}"})

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def feature(self, request, pk=None):
        product = self.get_object()
        product.is_featured = not product.is_featured
        product.save()
        return Response({"is_featured": product.is_featured})

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def featured(self, request):
        products = catalog_queryset(Product.objects.filter(
            is_featured=True,
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        ))
        page = self.paginate_queryset(products)

        serializer = ProductListSerializer(
            page if page is not None else products,
            many=True,
            context={"request": request},
        )

        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[AllowAny])
    def add_view(self, request, pk=None):
        product = self.get_object()
        Product.objects.filter(pk=product.pk).update(views_count=F("views_count") + 1)
        product.refresh_from_db(fields=["views_count"])

        if request.user.is_authenticated:
            RecentlyViewed.objects.update_or_create(user=request.user, product=product, defaults={"viewed_at": timezone.now()})

            recent_count = RecentlyViewed.objects.filter(
                user=request.user,
            ).count()

            if recent_count > 20:
                oldest = (
                    RecentlyViewed.objects.filter(
                        user=request.user,
                    )
                    .order_by("viewed_at")
                    .first()
                )

                if oldest:
                    oldest.delete()

        return Response({"views_count": product.views_count})

    @action(detail=False, methods=["get"])
    def recently_viewed(self, request):
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=401)

        recent = RecentlyViewed.objects.filter(user=request.user, product__status="approved", product__is_active=True).select_related("product").prefetch_related(main_image_prefetch("product__"))[:20]

        serializer = RecentlyViewedSerializer(
            recent,
            many=True,
            context={"request": request},
        )

        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def related(self, request, pk=None):
        product = self.get_object()

        related = catalog_queryset(Product.objects.filter(
            category=product.category,
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        ).exclude(id=product.id))[:10]

        serializer = ProductListSerializer(
            related,
            many=True,
            context={"request": request},
        )

        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def my_products(self, request):
        if not hasattr(request.user, "seller"):
            return Response({"error": "You are not a seller"}, status=403)

        products = catalog_queryset(Product.objects.filter(seller=request.user))
        page = self.paginate_queryset(products)

        serializer = ProductListSerializer(
            page if page is not None else products,
            many=True,
            context={"request": request},
        )

        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)


# ==================== Product Image Views ====================


class SellerProductComponentMixin:
    """Component edits invalidate moderation just like the parent product form."""

    @catalog_write
    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError
        try:
            raw_product_id = self.request.data.get("product")
            if isinstance(raw_product_id, bool) or isinstance(raw_product_id, float) and not raw_product_id.is_integer():
                raise ValueError
            product_id = int(raw_product_id)
            if not 0 < product_id <= 2 ** 63 - 1:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValidationError({"product": "A valid product ID is required."}) from exc
        product = get_object_or_404(Product.objects.select_for_update(), pk=product_id, seller=self.request.user)
        serializer.save(product=product)
        requeue_product_for_review(product)

    @catalog_write
    def perform_update(self, serializer):
        product = get_object_or_404(Product.objects.select_for_update(), pk=serializer.instance.product_id, seller=self.request.user)
        serializer.instance = get_object_or_404(self.get_queryset(), pk=serializer.instance.pk)
        serializer.save()
        requeue_product_for_review(product)

    @catalog_write
    def perform_destroy(self, instance):
        product = get_object_or_404(Product.objects.select_for_update(), pk=instance.product_id, seller=self.request.user)
        instance = get_object_or_404(self.get_queryset(), pk=instance.pk)
        instance.delete()
        requeue_product_for_review(product)


class ProductImageViewSet(SellerProductComponentMixin, viewsets.ModelViewSet):
    serializer_class = ProductImageSerializer
    permission_classes = [IsAuthenticated, IsVendor]

    def get_queryset(self):
        return ProductImage.objects.filter(product__seller=self.request.user)

# ==================== Product Variant Views ====================


class ProductVariantViewSet(SellerProductComponentMixin, viewsets.ModelViewSet):
    serializer_class = ProductVariantSerializer
    permission_classes = [IsAuthenticated, IsVendor]

    def get_queryset(self):
        return ProductVariant.objects.filter(product__seller=self.request.user)

# ==================== Wishlist Views ====================


class WishlistViewSet(viewsets.ModelViewSet):
    serializer_class = WishlistSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Wishlist.objects.filter(user=self.request.user, product__status=Product.StatusChoices.APPROVED, product__is_active=True).select_related("product").prefetch_related(main_image_prefetch("product__"))

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["delete"])
    def remove(self, request):
        product_id = request.data.get("product_id")
        Wishlist.objects.filter(user=request.user, product_id=product_id).delete()
        return Response({"message": "Removed from wishlist"})


class RecentlyViewedViewSet(viewsets.GenericViewSet, viewsets.mixins.ListModelMixin):
    """ViewSet for recently viewed products"""

    serializer_class = RecentlyViewedSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return RecentlyViewed.objects.filter(user=self.request.user, product__status="approved", product__is_active=True).select_related("product").prefetch_related(main_image_prefetch("product__"))[:20]


class ProductExportView(generics.GenericAPIView):
    """Export products to CSV or Excel"""

    permission_classes = [IsAuthenticated, IsProductAdmin]

    def get(self, request):
        format_type = request.query_params.get("export_format", "csv")
        products = catalog_queryset(Product.objects.all())

        if format_type == "csv":
            return self.export_csv(products)
        elif format_type == "excel":
            return self.export_excel(products)
        else:
            return Response({"error": "Invalid format. Use csv or excel"}, status=400)

    def export_csv(self, products):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="products.csv"'

        writer = csv.writer(response)
        writer.writerow(
            [
                "ID",
                "Name",
                "Price",
                "Stock",
                "Status",
                "Category",
                "Brand",
                "Created At",
            ]
        )

        for product in products:
            writer.writerow(
                [
                    product.id,
                    product.name,
                    product.price,
                    product.stock,
                    product.status,
                    product.category.name if product.category else "-",
                    product.brand.name if product.brand else "-",
                    product.created_at,
                ]
            )

        return response

    def export_excel(self, products):
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="products.xlsx"'

        wb = Workbook()
        ws = wb.active
        ws.title = "Products"

        ws.append(
            [
                "ID",
                "Name",
                "Price",
                "Stock",
                "Status",
                "Category",
                "Brand",
                "Created At",
            ]
        )

        for product in products:
            ws.append(
                [
                    product.id,
                    product.name,
                    product.price,
                    product.stock,
                    product.status,
                    product.category.name if product.category else "-",
                    product.brand.name if product.brand else "-",
                    product.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )

        wb.save(response)
        return response


class BulkProductUploadView(generics.CreateAPIView):
    """Upload multiple products via CSV/Excel"""

    permission_classes = [IsAuthenticated, IsVendor]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return Response({"error": "No file provided"}, status=400)

        if file.size > 8 * 1024 * 1024:
            return Response({"error": "Maximum import size is 8 MB."}, status=400)
        try:
            if file.name.lower().endswith(".csv"):
                df = pd.read_csv(file, nrows=1001)
            elif file.name.lower().endswith(".xlsx"):
                with zipfile.ZipFile(file) as archive:
                    if sum(entry.file_size for entry in archive.infolist()) > 64 * 1024 * 1024:
                        return Response({"error": "Expanded XLSX size exceeds 64 MB."}, status=400)
                file.seek(0)
                df = pd.read_excel(file, nrows=1001)
            else:
                return Response({"error": "Invalid file format. Use CSV or XLSX."}, status=400)
        except Exception:
            return Response({"error": "Unable to read the import file."}, status=400)
        if len(df) > 1000:
            return Response({"error": "Maximum import size is 1000 products."}, status=400)

        results = {"created": 0, "errors": []}

        for index, row in df.iterrows():
            data = {}
            for column, field in (("name", "name"), ("description", "description"), ("price", "price"), ("sku", "sku"), ("category_id", "category"), ("brand_id", "brand")):
                value = row.get(column)
                if pd.notna(value):
                    data[field] = int(value) if isinstance(value, float) and value.is_integer() else value
            serializer = ProductCreateUpdateSerializer(data=data, context={"request": request})
            if not serializer.is_valid():
                results["errors"].append({"row": index + 2, "error": serializer.errors})
                continue
            try:
                serializer.save(seller=request.user, status=Product.StatusChoices.PENDING)
                results["created"] += 1
            except Exception as exc:
                from rest_framework.exceptions import ValidationError
                if not isinstance(exc, ValidationError):
                    raise
                results["errors"].append({"row": index + 2, "error": exc.detail})

        return Response(results, status=201)


class ProductComparisonView(generics.GenericAPIView):
    """Compare multiple products"""

    permission_classes = [AllowAny]

    def get(self, request):
        raw_ids = request.query_params.get("ids", "").split(",")
        try:
            if not 1 <= len(raw_ids) <= 20:
                raise ValueError
            product_ids = [int(value.strip()) for value in raw_ids]
            if any(not 0 < value <= 2 ** 63 - 1 for value in product_ids) or len(product_ids) != len(set(product_ids)):
                raise ValueError
        except ValueError:
            return Response({"error": "Provide 1 to 20 distinct positive product IDs."}, status=400)

        products = list(catalog_queryset(Product.objects.filter(
            id__in=product_ids, status="approved", is_active=True,
        )).prefetch_related(Prefetch(
            "product_attributes", queryset=ProductAttribute.objects.select_related("attribute_value__attribute"),
        )))
        if len(products) != len(product_ids):
            return Response({"error": "Some products not found"}, status=404)

        comparison_data = {"products": [], "attributes": {}}

        for product in products:
            product_data = {
                "id": product.id,
                "name": product.name,
                "price": product.price,
                "final_price": product.final_price,
                "stock": product.stock,
                "image": ProductListSerializer().get_main_image(product),
                "attributes": {},
            }

            for attr in product.product_attributes.all():
                attr_name = attr.attribute_value.attribute.name
                attr_value = attr.attribute_value.value
                product_data["attributes"][attr_name] = attr_value

            comparison_data["products"].append(product_data)

        return Response(comparison_data)


class ProductQRCodeView(generics.GenericAPIView):
    permission_classes = [AllowAny]

    def get(self, request, product_id):
        try:
            product = Product.objects.get(id=product_id, status="approved", is_active=True)
        except Product.DoesNotExist:
            return Response(
                {"error": "Product not found"}, status=status.HTTP_404_NOT_FOUND
            )

        if not product.qr_code:
            return Response(
                {"error": "QR code not found"}, status=status.HTTP_404_NOT_FOUND
            )

        return FileResponse(product.qr_code.open("rb"), content_type="image/png")


class ProductLabelsView(generics.GenericAPIView):
    """Get list of available product labels"""

    permission_classes = [AllowAny]

    def get(self, request):
        labels = [
            {"value": "new", "display": " New", "icon": "🆕"},
            {"value": "bestseller", "display": "Bestseller", "icon": "⭐"},
            {"value": "discounted", "display": "Discounted", "icon": "💰"},
            {"value": "limited", "display": "Limited Edition", "icon": "🔒"},
            {"value": "preorder", "display": "Pre-order", "icon": "📦"},
        ]
        return Response(labels)
