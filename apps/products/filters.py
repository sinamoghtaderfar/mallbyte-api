# apps/products/filters.py

from django.db.models import Exists, F, OuterRef, Q
from django_filters import rest_framework as filters

from apps.inventory.models import Stock

from .models import Brand, Category, Product


class ProductFilter(filters.FilterSet):
    """Advanced filter for products"""

    min_price = filters.NumberFilter(field_name='price', lookup_expr='gte')
    max_price = filters.NumberFilter(field_name='price', lookup_expr='lte')
    category = filters.ModelMultipleChoiceFilter(
        field_name='category',
        queryset=Category.objects.all()
    )
    brand = filters.ModelMultipleChoiceFilter(
        field_name='brand',
        queryset=Brand.objects.all()
    )
    in_stock = filters.BooleanFilter(method='filter_in_stock')
    has_discount = filters.BooleanFilter(method='filter_has_discount')
    search = filters.CharFilter(method='filter_search')
    label = filters.CharFilter(method='filter_by_label')

    class Meta:
        model = Product
        fields = {
            'category': ['exact'],
            'brand': ['exact'],
            'price': ['gte', 'lte'],
            'status': ['exact'],
            'is_featured': ['exact'],
        }

    def filter_by_label(self, queryset, name, value):
        return queryset.filter(labels__contains=[value])

    def filter_in_stock(self, queryset, name, value):
        available = Stock.objects.filter(
            product_id=OuterRef("pk"), warehouse__is_active=True,
            quantity__gt=F("reserved_quantity"),
        )
        return queryset.annotate(_filter_in_stock=Exists(available)).filter(_filter_in_stock=value)

    def filter_has_discount(self, queryset, name, value):
        if value:
            return queryset.filter(compare_price__gt=F("price"))

        return queryset

    def filter_search(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(name__icontains=value) |
                Q(description__icontains=value) |
                Q(brand__name__icontains=value) |
                Q(sku__icontains=value)
            )

        return queryset
