from django_filters import rest_framework as filters
from apps.rbac import models
from .models import Product, Category, Brand


class ProductFilter(filters.FilterSet):
    """Advanced filter for products"""
    min_price = filters.NumberFilter(field_name='price', lookup_expr='gte')
    max_price = filters.NumberFilter(field_name='price', lookup_expr='lte')
    category = filters.ModelMultipleChoiceFilter(field_name='category', queryset=Category.objects.all())
    brand = filters.ModelMultipleChoiceFilter(field_name='brand', queryset=Brand.objects.all())
    in_stock = filters.BooleanFilter(method='filter_in_stock')
    has_discount = filters.BooleanFilter(method='filter_has_discount')
    search = filters.CharFilter(method='filter_search')
    
    class Meta:
        model = Product
        fields = {
            'category': ['exact'],
            'brand': ['exact'],
            'price': ['gte', 'lte'],
            'status': ['exact'],
            'is_featured': ['exact'],
        }
    
    def filter_in_stock(self, queryset, name, value):
        if value:
            return queryset.filter(stock__gt=0)
        return queryset
    
    def filter_has_discount(self, queryset, name, value):
        if value:
            return queryset.filter(compare_price__isnull=False)
        return queryset
    
    def filter_search(self, queryset, name, value):
        if value:
            return queryset.filter(
                models.Q(name__icontains=value) |
                models.Q(description__icontains=value) |
                models.Q(brand__name__icontains=value) |
                models.Q(sku__icontains=value)
            )
        return queryset