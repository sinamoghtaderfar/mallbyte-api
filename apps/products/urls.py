# apps/products/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CategoryViewSet, BrandViewSet, ProductViewSet,
    AttributeViewSet, AttributeValueViewSet, TagViewSet,
    ProductImageViewSet, ProductVariantViewSet
)

router = DefaultRouter()
router.register('categories', CategoryViewSet)
router.register('brands', BrandViewSet)
router.register('products', ProductViewSet)
router.register('attributes', AttributeViewSet)
router.register('attribute-values', AttributeValueViewSet)
router.register('tags', TagViewSet)
router.register('product-images', ProductImageViewSet, basename='product-image')  # اضافه کردن basename
router.register('product-variants', ProductVariantViewSet, basename='product-variant')  # اضافه کردن basename

urlpatterns = [
    path('', include(router.urls)),
]