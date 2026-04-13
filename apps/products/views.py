import csv
import pandas as pd
from rest_framework.parsers import MultiPartParser
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.http import FileResponse, HttpResponse
from openpyxl import Workbook
from rest_framework import generics
from .models import (
    Category, Brand, Product, ProductImage, ProductVariant,
    Attribute, AttributeValue, Review, Tag, Wishlist,RecentlyViewed
)
from .serializers import (
    CategorySerializer, BrandSerializer, ProductListSerializer,
    ProductDetailSerializer, ProductCreateUpdateSerializer,
    ProductImageSerializer, ProductVariantSerializer,
    AttributeSerializer, AttributeValueSerializer, RecentlyViewedSerializer, ReviewSerializer, TagSerializer,
    WishlistSerializer
)
from .filters import ProductFilter
from apps.rbac.permissions import IsVendor, IsProductAdmin
from .signals import add_product_to_recently_viewed


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
    
    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def featured(self, request):
        """Get featured products (public)"""
        products = Product.objects.filter(is_featured=True, status='approved', is_active=True)
        serializer = ProductListSerializer(products, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def add_view(self, request, pk=None):
        """Increase product view count (public)"""
        product = self.get_object()
        product.views_count += 1
        product.save()
        
        #Recently Viewed
        if request.user.is_authenticated:
            #delete old view if exists to avoid duplicates
            RecentlyViewed.objects.filter(user=request.user, product=product).delete()
            #create new view
            RecentlyViewed.objects.create(user=request.user, product=product)
            
            #save 20 recently viewed products
            recent_count = RecentlyViewed.objects.filter(user=request.user).count()
            if recent_count > 20:
                oldest = RecentlyViewed.objects.filter(user=request.user).order_by('viewed_at').first()
                if oldest:
                    oldest.delete()
        
        return Response({'views_count': product.views_count})
    @action(detail=False, methods=['get'])
    def recently_viewed(self, request):
        """Get recently viewed products for current user"""
        if not request.user.is_authenticated:
            return Response({'error': 'Authentication required'}, status=401)
        
        recent = RecentlyViewed.objects.filter(user=request.user)[:20]
        serializer = RecentlyViewedSerializer(recent, many=True, context={'request': request})
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
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


# ==================== Review Views ====================

class ReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewSerializer
    
    def get_queryset(self):
       
        queryset = Review.objects.filter(is_approved=True)
        product_id = self.request.query_params.get('product')
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return queryset
    
    def get_object(self):
     
        queryset = Review.objects.all()
        obj = get_object_or_404(queryset, pk=self.kwargs['pk'])
        self.check_object_permissions(self.request, obj)
        return obj
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def helpful(self, request, pk=None):
        review = self.get_object()
        review.helpful_count += 1
        review.save()
        return Response({'helpful_count': review.helpful_count})
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAuthenticated()]
# ==================== Wishlist Views ====================

class WishlistViewSet(viewsets.ModelViewSet):
    serializer_class = WishlistSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return Wishlist.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=False, methods=['delete'])
    def remove(self, request):
        product_id = request.data.get('product_id')
        Wishlist.objects.filter(user=request.user, product_id=product_id).delete()
        return Response({'message': 'Removed from wishlist'})

class RecentlyViewedViewSet(viewsets.GenericViewSet, viewsets.mixins.ListModelMixin):
    """ViewSet for recently viewed products"""
    
    serializer_class = RecentlyViewedSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return RecentlyViewed.objects.filter(user=self.request.user)[:20]



class ProductExportView(generics.GenericAPIView):
    """Export products to CSV or Excel"""
    permission_classes = [IsAuthenticated, IsProductAdmin]
    
    def get(self, request):
        print(">>> ProductExportView called")
        format_type = request.query_params.get('export_format', 'csv')
        products = Product.objects.all()
        
        if format_type == 'csv':
            return self.export_csv(products)
        elif format_type == 'excel':
            return self.export_excel(products)
        else:
            return Response({'error': 'Invalid format. Use csv or excel'}, status=400)
    
    def export_csv(self, products):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="products.csv"'
        
        writer = csv.writer(response) 
        writer.writerow(['ID', 'Name', 'Price', 'Stock', 'Status', 'Category', 'Brand', 'Created At'])
        
        for product in products:
            writer.writerow([
                product.id,
                product.name,
                product.price,
                product.stock,
                product.status,
                product.category.name if product.category else '-',
                product.brand.name if product.brand else '-',
                product.created_at
            ])
        
        return response
    
    def export_excel(self, products):
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="products.xlsx"'
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Products"
        
        ws.append(['ID', 'Name', 'Price', 'Stock', 'Status', 'Category', 'Brand', 'Created At'])
        
        for product in products:
            ws.append([
                product.id,
                product.name,
                product.price,
                product.stock,
                product.status,
                product.category.name if product.category else '-',
                product.brand.name if product.brand else '-',
                product.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
        
        wb.save(response)
        return response
    
    

class BulkProductUploadView(generics.CreateAPIView):
    """Upload multiple products via CSV/Excel"""
    permission_classes = [IsAuthenticated, IsVendor]
    parser_classes = [MultiPartParser]
    
    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'No file provided'}, status=400)
        
        # read file
    
        if file.name.endswith('.csv'):
            df = pd.read_csv(file)
        elif file.name.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file)
        else:
            return Response({'error': 'Invalid file format. Use CSV or Excel'}, status=400)
        
        results = {'created': 0, 'errors': []}
        
        for index, row in df.iterrows():
            try:
                product = Product.objects.create(
                    seller=request.user,
                    name=row['name'],
                    description=row.get('description', ''),
                    price=row['price'],
                    sku=row['sku'],
                    stock=row.get('stock', 0),
                    category_id=row['category_id'],
                    brand_id=row.get('brand_id'),
                    status='pending'
                )
                results['created'] += 1
            except Exception as e:
                results['errors'].append({'row': index + 2, 'error': str(e)})
        
        return Response(results, status=201)
class ProductComparisonView(generics.GenericAPIView):
    """Compare multiple products"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        product_ids = request.query_params.get('ids', '').split(',')
        if not product_ids or not product_ids[0]:
            return Response({'error': 'Provide product IDs: ?ids=1,2,3'}, status=400)
        
        products = Product.objects.filter(id__in=product_ids, status='approved', is_active=True)
        
        if products.count() != len(product_ids):
            return Response({'error': 'Some products not found'}, status=404)
        
        comparison_data = {
            'products': [],
            'attributes': {}
        }
        
        for product in products:
            product_data = {
                'id': product.id,
                'name': product.name,
                'price': product.price,
                'final_price': product.final_price,
                'stock': product.stock,
                'image': product.images.filter(is_main=True).first().image.url if product.images.filter(is_main=True).first() else None,
                'attributes': {}
            }
            
            
            for attr in product.product_attributes.all():
                attr_name = attr.attribute_value.attribute.name
                attr_value = attr.attribute_value.value
                product_data['attributes'][attr_name] = attr_value
            
            comparison_data['products'].append(product_data)
        
        return Response(comparison_data)



class ProductQRCodeView(generics.GenericAPIView):
    permission_classes = [AllowAny]

    def get(self, request, product_id):
        try:
            product = Product.objects.get(id=product_id, status='approved')
        except Product.DoesNotExist:
            return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

        if not product.qr_code:
            return Response({'error': 'QR code not found'}, status=status.HTTP_404_NOT_FOUND)

        return FileResponse(product.qr_code.open('rb'), content_type='image/png')
        

class ProductLabelsView(generics.GenericAPIView):
    """Get list of available product labels"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        labels = [
            {'value': 'new', 'display': ' New', 'icon': '🆕'},
            {'value': 'bestseller', 'display': 'Bestseller', 'icon': '⭐'},
            {'value': 'discounted', 'display': 'Discounted', 'icon': '💰'},
            {'value': 'limited', 'display': 'Limited Edition', 'icon': '🔒'},
            {'value': 'preorder', 'display': 'Pre-order', 'icon': '📦'},
        ]
        return Response(labels)