from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import (
    Category, Brand, Product, ProductImage, ProductVariant,
    Attribute, AttributeValue, Tag
)
from .serializers import (
    CategorySerializer, BrandSerializer, ProductListSerializer,
    ProductDetailSerializer, ProductCreateUpdateSerializer,
    ProductImageSerializer, ProductVariantSerializer,
    AttributeSerializer, AttributeValueSerializer, TagSerializer
)
from .filters import ProductFilter
from apps.rbac.permissions import IsVendor, IsProductAdmin


# ==================== Category Views ====================

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAuthenticated(), IsProductAdmin()]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        parent = self.request.query_params.get('parent')
        if parent == 'null' or parent is None:
            queryset = queryset.filter(parent__isnull=True)
        elif parent:
            queryset = queryset.filter(parent_id=parent)
        return queryset


# ==================== Brand Views ====================

class BrandViewSet(viewsets.ModelViewSet):
    queryset = Brand.objects.filter(is_active=True)
    serializer_class = BrandSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAuthenticated(), IsProductAdmin()]


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
        attribute_id = self.request.query_params.get('attribute')
        if attribute_id:
            queryset = queryset.filter(attribute_id=attribute_id)
        return queryset


# ==================== Tag Views ====================

class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    
    def get_permissions(self):
        if self.action in ['list']:
            return [AllowAny()]
        return [IsAuthenticated(), IsProductAdmin()]


# ==================== Product Views ====================

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ['name', 'description', 'sku', 'brand__name']
    ordering_fields = ['price', 'created_at', 'views_count', 'stock']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ProductCreateUpdateSerializer
        return ProductDetailSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        elif self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), IsVendor()]
        elif self.action in ['approve', 'reject', 'feature']:
            return [IsAuthenticated(), IsProductAdmin()]
        return super().get_permissions()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        if user.is_authenticated and (user.is_superuser or user.is_staff):
            return queryset
        
        if user.is_authenticated and hasattr(user, 'seller') and user.seller.is_verified:
            return queryset.filter(seller=user)
        
        return queryset.filter(status='approved', is_active=True)
    
    def perform_create(self, serializer):
        serializer.save(
            seller=self.request.user,
            status='pending'
        )
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        product = self.get_object()
        product.status = 'approved'
        product.approved_by = request.user
        product.approved_at = timezone.now()
        product.save()
        return Response({'message': 'Product approved successfully'})
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        product = self.get_object()
        reason = request.data.get('reason', 'No reason provided')
        product.status = 'rejected'
        product.save()
        return Response({'message': f'Product rejected. Reason: {reason}'})
    
    @action(detail=True, methods=['post'])
    def feature(self, request, pk=None):
        product = self.get_object()
        product.is_featured = not product.is_featured
        product.save()
        return Response({'is_featured': product.is_featured})
    
    @action(detail=True, methods=['post'])
    def add_view(self, request, pk=None):
        product = self.get_object()
        product.views_count += 1
        product.save()
        return Response({'views_count': product.views_count})
    
    @action(detail=True, methods=['get'])
    def related(self, request, pk=None):
        product = self.get_object()
        related = Product.objects.filter(
            category=product.category,
            status='approved',
            is_active=True
        ).exclude(id=product.id)[:10]
        serializer = ProductListSerializer(related, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def featured(self, request):
        products = Product.objects.filter(is_featured=True, status='approved', is_active=True)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def my_products(self, request):
        if not hasattr(request.user, 'seller'):
            return Response({'error': 'You are not a seller'}, status=403)
        products = Product.objects.filter(seller=request.user)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)


# ==================== Product Image Views ====================

class ProductImageViewSet(viewsets.ModelViewSet):
    serializer_class = ProductImageSerializer
    permission_classes = [IsAuthenticated, IsVendor]
    
    def get_queryset(self):
        return ProductImage.objects.filter(product__seller=self.request.user)
    
    def perform_create(self, serializer):
        product_id = self.request.data.get('product')
        product = get_object_or_404(Product, id=product_id, seller=self.request.user)
        serializer.save(product=product)



# ==================== Product Variant Views ====================
class ProductVariantViewSet(viewsets.ModelViewSet):
    serializer_class = ProductVariantSerializer
    permission_classes = [IsAuthenticated, IsVendor]
    
    def get_queryset(self):
        return ProductVariant.objects.filter(product__seller=self.request.user)
    
    def perform_create(self, serializer):
        product_id = self.request.data.get('product')
        product = get_object_or_404(Product, id=product_id, seller=self.request.user)
        serializer.save(product=product)