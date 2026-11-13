from django.db.models import F, IntegerField, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.products.models import ProductImage


def main_image_prefetch(prefix=""):
    return Prefetch(prefix + "images", queryset=ProductImage.objects.filter(is_main=True).order_by("order", "pk"), to_attr="_catalog_main_images")


def catalog_queryset(queryset):
    return queryset.select_related("brand", "category").prefetch_related(main_image_prefetch()).annotate(
        _catalog_stock=Coalesce(Sum("stock_items__quantity"), Value(0), output_field=IntegerField()),
        _catalog_reserved=Coalesce(Sum("stock_items__reserved_quantity"), Value(0), output_field=IntegerField()),
        _catalog_available=Coalesce(
            Sum(
                F("stock_items__quantity") - F("stock_items__reserved_quantity"),
                filter=Q(stock_items__warehouse__is_active=True),
            ),
            Value(0), output_field=IntegerField(),
        ),
    ).order_by("-created_at", "-pk")
