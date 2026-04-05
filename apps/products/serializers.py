from rest_framework import serializers

from apps.rbac import models
from .models import (
    Category, Brand, Product, ProductImage, ProductVariant,
    Attribute, AttributeValue, ProductAttribute, Review, Tag, Wishlist, 
)

class CategorySerializer(serializers.ModelSerializer):
    """Serializer for Category model"""
    
    children = serializers.SerializerMethodField()
    parent_name = serializers.ReadOnlyField(source='parent.name')
    
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'parent', 'parent_name', 'children',
                  'description', 'image', 'is_active', 'order', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']
    
    def get_children(self, obj):
        return CategorySerializer(obj.children.filter(is_active=True), many=True).data

class BrandSerializer(serializers.ModelSerializer):
    """Serializer for Brand model"""
    
    class Meta:
        model = Brand
        fields = ['id', 'name', 'slug', 'logo', 'description', 'website', 
                  'is_active', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']

class ProductImageSerializer(serializers.ModelSerializer):
    """Serializer for ProductImage model"""
    
    class Meta:
        model = ProductImage  
        fields = ['id', 'image', 'alt_text', 'is_main', 'order', 'created_at']
        read_only_fields = ['id', 'created_at']
        
class AttributeValueSerializer(serializers.ModelSerializer):
    """Serializer for AttributeValue model"""
    attribute_name = serializers.ReadOnlyField(source='attribute.name')
    class Meta:
        model = AttributeValue
        fields = ['id', 'attribute', 'attribute_name', 'value', 'slug']
        read_only_fields = ['id', 'slug']

class AttributeSerializer(serializers.ModelSerializer):
    """Serializer for Attribute model"""
    values = AttributeValueSerializer(many=True, read_only=True)
    
    class Meta:
        model = Attribute
        fields = ['id', 'name', 'slug', 'is_filterable', 'values', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']
        
class TagSerializer(serializers.ModelSerializer):
    """Serializer for Tag model"""
    
    class Meta:
        model = Tag
        fields = ['id', 'name', 'slug', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']

class ProductListSerializer(serializers.ModelSerializer):
    """Serializer for listing products"""
    main_image = serializers.SerializerMethodField()
    brand_name = serializers.ReadOnlyField(source='brand.name')
    category_name = serializers.ReadOnlyField(source='category.name')
    final_price = serializers.ReadOnlyField()
    
    class Meta:
        model = Product
        fields = ['id', 'name', 'slug', 'main_image', 'price', 'compare_price', 
                  'final_price', 'brand_name', 'category_name', 'stock', 
                  'is_featured', 'views_count', 'created_at']
    
    def get_main_image(self, obj):
        main_image = obj.images.filter(is_main=True).first()
        if main_image:
            return main_image.image.url
        return None
class ProductVariantSerializer(serializers.ModelSerializer):
    """Serializer for ProductVariant model"""
    final_price = serializers.ReadOnlyField()
    
    class Meta:
        model = ProductVariant
        fields = ['id', 'name', 'sku', 'price', 'compare_price', 'final_price', 
                  'stock', 'is_default', 'created_at']
        read_only_fields = ['id', 'created_at']
        
class ProductDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for single product"""
    seller_name = serializers.ReadOnlyField(source='seller.full_name')
    seller_phone = serializers.ReadOnlyField(source='seller.phone')
    category_name = serializers.ReadOnlyField(source='category.name')
    brand_name = serializers.ReadOnlyField(source='brand.name')
    brand_logo = serializers.SerializerMethodField()
    images = ProductImageSerializer(many=True, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    attributes = serializers.SerializerMethodField()
    tags = TagSerializer(many=True, read_only=True)
    final_price = serializers.ReadOnlyField()
    average_rating = serializers.SerializerMethodField()
    reviews_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = ['id', 'name', 'slug', 'description', 'short_description',
                  'price', 'compare_price', 'final_price', 'cost_per_item',
                  'seller_name', 'seller_phone', 'category', 'category_name',
                  'brand', 'brand_name', 'brand_logo', 'sku', 'stock',
                  'low_stock_threshold', 'weight', 'length', 'width', 'height',
                  'status', 'is_active', 'is_featured', 'images', 'variants',
                  'attributes', 'tags', 'average_rating', 'reviews_count',
                  'views_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'slug', 'views_count', 'created_at', 'updated_at']
    
    def get_attributes(self, obj):
        product_attrs = obj.product_attributes.select_related('attribute_value__attribute')
        return [
            {
                'attribute': pa.attribute_value.attribute.name,
                'attribute_slug': pa.attribute_value.attribute.slug,
                'value': pa.attribute_value.value,
                'value_slug': pa.attribute_value.slug
            }
            for pa in product_attrs
        ]
    
    def get_average_rating(self, obj):
        
        #from apps.reviews.models import Review
        #result = Review.objects.filter(product=obj).aggregate(avg=models.Avg('rating'))
       
        return 0
    
    def get_reviews_count(self, obj):
        #return obj.reviews.count()
        return 0
    
    def get_brand_logo(self, obj):
        if obj.brand and obj.brand.logo:
            return obj.brand.logo.url
        return None
    
class ProductCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating products (for vendors)"""
    id = serializers.IntegerField(read_only=True)
    images = ProductImageSerializer(many=True, required=False)
    variants = ProductVariantSerializer(many=True, required=False)
    tags = serializers.SlugRelatedField(
        many=True, slug_field='name', queryset=Tag.objects.all(), required=False
    )
    
    class Meta:
        model = Product
        fields = ['id', 'name', 'description', 'short_description', 'price', 'compare_price',
                  'cost_per_item', 'category', 'brand', 'sku', 'stock',
                  'low_stock_threshold', 'weight', 'length', 'width', 'height',
                  'is_featured', 'images', 'variants', 'tags']
    
    def create(self, validated_data):
        images_data = validated_data.pop('images', [])
        variants_data = validated_data.pop('variants', [])
        tags_data = validated_data.pop('tags', [])
        
        product = Product.objects.create(**validated_data)
        
        for image_data in images_data:
            ProductImage.objects.create(product=product, **image_data)
        
        for variant_data in variants_data:
            ProductVariant.objects.create(product=product, **variant_data)
        
        product.tags.set(tags_data)
        
        return product
    
    def update(self, instance, validated_data):
        images_data = validated_data.pop('images', [])
        variants_data = validated_data.pop('variants', [])
        tags_data = validated_data.pop('tags', [])
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update images
        if images_data:
            instance.images.all().delete()
            for image_data in images_data:
                ProductImage.objects.create(product=instance, **image_data)
        
        # Update variants
        if variants_data:
            instance.variants.all().delete()
            for variant_data in variants_data:
                ProductVariant.objects.create(product=instance, **variant_data)
        
        # Update tags
        if tags_data:
            instance.tags.set(tags_data)
        
        return instance
    

class ReviewSerializer(serializers.ModelSerializer):
    user_name = serializers.ReadOnlyField(source='user.full_name')
    user_phone = serializers.ReadOnlyField(source='user.phone')
    
    class Meta:
        model = Review
        fields = ['id', 'product', 'user', 'user_name', 'user_phone',
                  'rating', 'title', 'comment', 'is_approved', 
                  'helpful_count', 'created_at']
        read_only_fields = ['id', 'user', 'is_approved', 'helpful_count', 'created_at']

class WishlistSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    product_price = serializers.ReadOnlyField(source='product.price')
    product_image = serializers.SerializerMethodField()
    
    class Meta:
        model = Wishlist
        fields = ['id', 'product', 'product_name', 'product_price', 'product_image', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def get_product_image(self, obj):
        main_image = obj.product.images.filter(is_main=True).first()
        if main_image:
            return main_image.image.url
        return None