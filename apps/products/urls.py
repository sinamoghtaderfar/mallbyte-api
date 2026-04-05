# apps/products/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CategoryViewSet, BrandViewSet, ProductViewSet,
    AttributeViewSet, AttributeValueViewSet, TagViewSet,
    ProductImageViewSet, ProductVariantViewSet,
    ReviewViewSet, WishlistViewSet
)

router = DefaultRouter()
router.register('categories', CategoryViewSet)
router.register('brands', BrandViewSet)
router.register('products', ProductViewSet)
router.register('attributes', AttributeViewSet)
router.register('attribute-values', AttributeValueViewSet)
router.register('tags', TagViewSet)
router.register('product-images', ProductImageViewSet, basename='product-image')
router.register('product-variants', ProductVariantViewSet, basename='product-variant')
#router.register('reviews', ReviewViewSet, basename='review')
router.register('wishlist', WishlistViewSet, basename='wishlist')

urlpatterns = [
    path('', include(router.urls)),
    
    path('reviews/', ReviewViewSet.as_view({'get': 'list', 'post': 'create'}), name='review-list'),
    path('reviews/<int:pk>/', ReviewViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'}), name='review-detail'),
    path('reviews/<int:pk>/helpful/', ReviewViewSet.as_view({'post': 'helpful'}), name='review-helpful'),
]