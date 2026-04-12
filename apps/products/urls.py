# apps/products/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    BulkProductUploadView, CategoryViewSet, BrandViewSet, ProductComparisonView, ProductExportView, ProductViewSet,
    AttributeViewSet, AttributeValueViewSet, TagViewSet,
    ProductImageViewSet, ProductVariantViewSet,
    ReviewViewSet, WishlistViewSet, RecentlyViewedViewSet
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

router.register('recently-viewed', RecentlyViewedViewSet, basename='recently-viewed')


urlpatterns = [
    path('', include(router.urls)),
    
    path('reviews/', ReviewViewSet.as_view({'get': 'list', 'post': 'create'}), name='review-list'),
    path('reviews/<int:pk>/', ReviewViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'}), name='review-detail'),
    path('reviews/<int:pk>/helpful/', ReviewViewSet.as_view({'post': 'helpful'}), name='review-helpful'),
    
    path('bulk-upload/', BulkProductUploadView.as_view(), name='bulk-upload'),
    
    path('export/', ProductExportView.as_view(), name='product-export'),
    
    path('compare/', ProductComparisonView.as_view(), name='product-compare'),
    
    
]


