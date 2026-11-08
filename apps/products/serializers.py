from functools import wraps

from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import (
    Attribute,
    AttributeValue,
    Brand,
    Category,
    Product,
    ProductImage,
    ProductVariant,
    RecentlyViewed,
    Tag,
    Wishlist,
)


def catalog_write(func):
    """Translate constraint races after rolling back the complete nested write."""
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            with transaction.atomic():
                return func(*args, **kwargs)
        except IntegrityError as exc:
            raise serializers.ValidationError({"detail": "Catalog data conflicts with an existing SKU, image or variant constraint."}) from exc
    return wrapped


def validate_compare_price(attrs, instance):
    price = attrs.get("price", getattr(instance, "price", None))
    compare = attrs.get("compare_price", getattr(instance, "compare_price", None))
    if price is not None and compare is not None and compare < price:
        raise serializers.ValidationError({"compare_price": "Compare price must be at least the current selling price."})
    return attrs


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
        ancestors = self.context.get("category_ancestors", set())
        if obj.pk in ancestors:
            return []
        context = {**self.context, "category_ancestors": ancestors | {obj.pk}}
        children = self.context.get("category_children")
        queryset = children.get(obj.pk, []) if children is not None else obj.children.filter(is_active=True)
        return CategorySerializer(queryset, many=True, context=context).data

    def validate_parent(self, parent):
        seen = set()
        cursor = parent
        while cursor:
            if cursor.pk in seen or self.instance and cursor.pk == self.instance.pk:
                raise serializers.ValidationError("Category hierarchy cannot contain a cycle.")
            seen.add(cursor.pk)
            cursor = cursor.parent
        return parent

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

    def validate_image(self, image):
        if image.size > 8 * 1024 * 1024:
            raise serializers.ValidationError("Maximum image upload size is 8 MB.")
        return image
        
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
    """Optimized public catalog representation using optional queryset aggregates."""

    main_image = serializers.SerializerMethodField()
    brand_name = serializers.ReadOnlyField(source="brand.name")
    category_name = serializers.ReadOnlyField(source="category.name")
    final_price = serializers.ReadOnlyField()
    stock = serializers.SerializerMethodField()
    available_stock = serializers.SerializerMethodField()
    reserved_stock = serializers.SerializerMethodField()
    label_display = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "main_image", "price", "compare_price",
            "final_price", "brand_name", "category_name",
            "stock", "available_stock", "reserved_stock",
            "is_featured", "views_count", "created_at",
            "barcode", "labels", "label_display",
        ]

    def get_stock(self, obj):
        return obj._catalog_stock if hasattr(obj, "_catalog_stock") else obj.stock

    def get_reserved_stock(self, obj):
        return obj._catalog_reserved if hasattr(obj, "_catalog_reserved") else obj.reserved_stock

    def get_available_stock(self, obj):
        if hasattr(obj, "_catalog_stock") and hasattr(obj, "_catalog_reserved"):
            return obj._catalog_stock - obj._catalog_reserved
        return obj.available_stock

    def get_label_display(self, obj):
        labels_map = {
            "new": "New",
            "bestseller": "Bestseller",
            "discounted": "Discounted",
            "limited": "Limited Edition",
            "preorder": "Pre-order",
        }
        return [labels_map.get(label, label) for label in (obj.labels or [])]

    def get_main_image(self, obj):
        # Public listing querysets prefetch main images to avoid a query per product.
        if hasattr(obj, "_catalog_main_images"):
            image = next(iter(obj._catalog_main_images), None)
        else:
            image = obj.images.filter(is_main=True).first()
        return image.image.url if image else None


class ProductVariantSerializer(serializers.ModelSerializer):
    """Serializer for ProductVariant model"""
    final_price = serializers.ReadOnlyField()

    def validate(self, attrs):
        return validate_compare_price(attrs, self.instance)
    
    class Meta:
        model = ProductVariant
        fields = ['id', 'name', 'sku', 'price', 'compare_price', 'final_price', 
                  'stock', 'is_default', 'created_at']
        read_only_fields = ['id', 'created_at']
        
class NestedProductVariantSerializer(ProductVariantSerializer):
    class Meta(ProductVariantSerializer.Meta):
        extra_kwargs = {"sku": {"validators": []}}


class ProductDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for single product"""
    seller_name = serializers.ReadOnlyField(source='seller.full_name')
    seller_email = serializers.ReadOnlyField(source="seller.email")
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
    
    stock = serializers.IntegerField(read_only=True)
    available_stock = serializers.IntegerField(read_only=True)
    reserved_stock = serializers.IntegerField(read_only=True)
    is_in_stock = serializers.BooleanField(read_only=True)
    
    label_display = serializers.SerializerMethodField()
    class Meta:
        model = Product
        fields = ['id', 'name', 'slug', 'description', 'short_description',
                'price', 'compare_price', 'final_price', 'cost_per_item',
                "seller_name",
                "seller_email",
                "category",
                "category_name",
                "brand",
                "brand_name",
                "brand_logo",
                "sku",
                "stock",
                'available_stock', 'reserved_stock', 'is_in_stock',
                'low_stock_threshold', 'weight', 'length', 'width', 'height',
                'status', 'is_active', 'is_featured', 'images', 'variants',
                'attributes', 'tags', 'average_rating', 'reviews_count',
                'views_count', 'created_at', 'updated_at', 'barcode','labels','label_display',]
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
        return obj.avrage_rating
    
    def get_reviews_count(self, obj):
        return obj.reviews_count
    
    def get_brand_logo(self, obj):
        if obj.brand and obj.brand.logo:
            return obj.brand.logo.url
        return None
    
    def get_label_display(self, obj):
        labels_map = {
            'new': 'New',
            'bestseller': 'Bestseller',
            'discounted': 'Discounted',
            'limited': 'Limited Edition',
            'preorder': 'Pre-order',
    }
        return [labels_map.get(label, label) for label in (obj.labels or [])]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        from apps.rbac.permissions import user_has_active_role
        privileged = bool(user and user.is_authenticated and (
            user.pk == instance.seller_id or user.is_superuser or user_has_active_role(user, "product_admin")
        ))
        if not privileged:
            data.pop("cost_per_item", None)
            data.pop("seller_email", None)
        return data


class ProductCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating products (for vendors)"""
    id = serializers.IntegerField(read_only=True)
    images = ProductImageSerializer(many=True, required=False)
    variants = NestedProductVariantSerializer(many=True, required=False)
    tags = serializers.SlugRelatedField(
        many=True, slug_field='name', queryset=Tag.objects.all(), required=False
    )
    stock = serializers.IntegerField(read_only=True)
    available_stock = serializers.IntegerField(read_only=True)
    reserved_stock = serializers.IntegerField(read_only=True)
    is_featured = serializers.BooleanField(read_only=True)
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'short_description',
            'price', 'compare_price', 'cost_per_item',
            'category', 'brand', 'sku',
            'stock', 'available_stock', 'reserved_stock',
            'low_stock_threshold', 'weight', 'length', 'width', 'height',
            'is_featured', 'images', 'variants', 'tags',
            'barcode', 'labels',
        ]
    
    def validate(self, attrs):
        return validate_compare_price(attrs, self.instance)

    def validate_labels(self, labels):
        if not isinstance(labels, list) or any(not isinstance(label, str) or label not in Product.LabelChoices.values for label in labels):
            raise serializers.ValidationError("Labels must be a list of supported product label values.")
        return list(dict.fromkeys(labels))

    def validate_images(self, images):
        if sum(bool(image.get("is_main")) for image in images) > 1:
            raise serializers.ValidationError("Only one main image is allowed.")
        return images

    def validate_variants(self, variants):
        skus = [variant["sku"] for variant in variants]
        existing = ProductVariant.objects.filter(sku__in=skus)
        if self.instance:
            existing = existing.exclude(product=self.instance)
        if len(skus) != len(set(skus)) or existing.exists():
            raise serializers.ValidationError("Variant SKUs must be unique.")
        if sum(bool(variant.get("is_default")) for variant in variants) > 1:
            raise serializers.ValidationError("Only one default variant is allowed.")
        return variants

    @catalog_write
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
    
    @catalog_write
    def update(self, instance, validated_data):
        # Re-read under the same lock used by approve/reject before changing data.
        instance = Product.objects.select_for_update().get(pk=instance.pk)
        images_data = validated_data.pop('images', None)
        variants_data = validated_data.pop('variants', None)
        tags_data = validated_data.pop('tags', None)
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.status = Product.StatusChoices.PENDING
        instance.approved_by = None
        instance.approved_at = None
        instance.save()
        
        # Update images
        if images_data is not None:
            instance.images.all().delete()
            for image_data in images_data:
                ProductImage.objects.create(product=instance, **image_data)
        
        # Update variants
        if variants_data is not None:
            instance.variants.all().delete()
            for variant_data in variants_data:
                ProductVariant.objects.create(product=instance, **variant_data)
        
        # Update tags
        if tags_data is not None:
            instance.tags.set(tags_data)
        
        return instance
    

class WishlistSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(status=Product.StatusChoices.APPROVED, is_active=True))
    product_name = serializers.ReadOnlyField(source='product.name')
    product_price = serializers.ReadOnlyField(source='product.price')
    product_image = serializers.SerializerMethodField()

    def validate_product(self, product):
        request = self.context.get("request")
        if self.instance and request and Wishlist.objects.filter(user=request.user, product=product).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("This product is already in your wishlist.")
        return product

    def create(self, validated_data):
        item, _ = Wishlist.objects.get_or_create(**validated_data)
        return item
    
    class Meta:
        model = Wishlist
        fields = ['id', 'product', 'product_name', 'product_price', 'product_image', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def get_product_image(self, obj):
        return ProductListSerializer().get_main_image(obj.product)
    
class RecentlyViewedSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source="product.name")
    product_price = serializers.ReadOnlyField(source="product.price")
    product_image = serializers.SerializerMethodField()
    
    class Meta:
        model = RecentlyViewed
        fields = ['id', 'product', 'product_name', 'product_price', 'product_image', 'viewed_at']
        read_only_fields = ['id', 'viewed_at']
        
    def get_product_image(self, obj):
        return ProductListSerializer().get_main_image(obj.product)
