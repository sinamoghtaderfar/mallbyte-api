# apps/products/urls.py

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AttributeValueViewSet, AttributeViewSet, BrandViewSet, BulkProductUploadView, CategoryViewSet, ProductComparisonView, ProductExportView, ProductImageViewSet, ProductLabelsView, ProductQRCodeView, ProductVariantViewSet, ProductViewSet, RecentlyViewedViewSet, TagViewSet, WishlistViewSet

router = DefaultRouter()
router.register('categories', CategoryViewSet)
router.register('brands', BrandViewSet)
router.register('products', ProductViewSet)
router.register('attributes', AttributeViewSet)
router.register('attribute-values', AttributeValueViewSet)
router.register('tags', TagViewSet)
router.register('product-images', ProductImageViewSet, basename='product-image')
router.register('product-variants', ProductVariantViewSet, basename='product-variant')
router.register('wishlist', WishlistViewSet, basename='wishlist')

router.register('recently-viewed', RecentlyViewedViewSet, basename='recently-viewed')


urlpatterns = [
    path('', include(router.urls)),
    
    
    path('bulk-upload/', BulkProductUploadView.as_view(), name='bulk-upload'),
    
    path('export/', ProductExportView.as_view(), name='product-export'),
    
    path('compare/', ProductComparisonView.as_view(), name='product-compare'),
    
    path('products/<int:product_id>/qr-code/', ProductQRCodeView.as_view(), name='product-qr-code'),
    
    path('labels/', ProductLabelsView.as_view(), name='product-labels'),


]


