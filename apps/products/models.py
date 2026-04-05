# apps/products/models.py

from django.db import models
from django.utils.text import slugify
from django.contrib.auth import get_user_model

User = get_user_model()


class Category(models.Model):
    """Product categories (hierarchical)"""
    name = models.CharField(max_length=100, verbose_name="Category Name")
    slug = models.SlugField(unique=True, verbose_name="Slug")
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='children',
        verbose_name="Parent Category"
    )
    description = models.TextField(blank=True, verbose_name="Description")
    image = models.ImageField(upload_to='categories/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0, verbose_name="Display Order")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Brand(models.Model):
    """Product brands"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    logo = models.ImageField(upload_to='brands/', null=True, blank=True)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Brand"
        verbose_name_plural = "Brands"
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Product(models.Model):
    """Main product model"""
    
    class StatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        DRAFT = 'draft', 'Draft'
    
    seller = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='products',
        limit_choices_to={'is_seller': True},
        verbose_name="Seller"
    )
    category = models.ForeignKey(
        Category, 
        on_delete=models.CASCADE, 
        related_name='products',
        verbose_name="Category"
    )
    brand = models.ForeignKey(
        Brand, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='products',
        verbose_name="Brand"
    )
    name = models.CharField(max_length=255, verbose_name="Product Name")
    slug = models.SlugField(unique=True, verbose_name="Slug")
    description = models.TextField(verbose_name="Description")
    short_description = models.TextField(max_length=500, blank=True)
    
    avrage_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    reviews_count = models.PositiveIntegerField(default=0)
    # Pricing
    price = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Price")
    compare_price = models.DecimalField(
        max_digits=12, decimal_places=0, 
        null=True, blank=True, 
        verbose_name="Compare Price (was...)"
    )
    cost_per_item = models.DecimalField(
        max_digits=12, decimal_places=0, 
        null=True, blank=True,
        verbose_name="Cost per item"
    )
    
    # Status
    status = models.CharField(
        max_length=20, 
        choices=StatusChoices.choices, 
        default=StatusChoices.PENDING,
        verbose_name="Status"
    )
    
    tags = models.ManyToManyField(
        'Tag',
        related_name='products',
        blank=True,
        verbose_name="Tags"
    )
    is_active = models.BooleanField(default=True, verbose_name="Is Active")
    is_featured = models.BooleanField(default=False, verbose_name="Featured Product")
    
    # Inventory
    sku = models.CharField(max_length=100, unique=True, verbose_name="SKU")
    stock = models.PositiveIntegerField(default=0, verbose_name="Stock Quantity")
    low_stock_threshold = models.PositiveIntegerField(default=5, verbose_name="Low Stock Alert")
    
    # Weight & dimensions (for shipping)
    weight = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    length = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    width = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # SEO
    meta_title = models.CharField(max_length=200, blank=True)
    meta_description = models.TextField(max_length=500, blank=True)
    
    # Timestamps
    approved_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='approved_products',
        verbose_name="Approved By"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    views_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['status', 'is_active']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Product.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)
    
    @property
    def final_price(self):
        """Get final price (with discount if any)"""
        return self.compare_price if self.compare_price else self.price


class ProductImage(models.Model):
    """Product images gallery"""
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='images',
        verbose_name="Product"
    )
    image = models.ImageField(upload_to='products/', verbose_name="Image")
    alt_text = models.CharField(max_length=255, blank=True, verbose_name="Alt Text")
    is_main = models.BooleanField(default=False, verbose_name="Main Image")
    order = models.IntegerField(default=0, verbose_name="Display Order")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Product Image"
        verbose_name_plural = "Product Images"
        ordering = ['order']

    def __str__(self):
        return f"{self.product.name} - Image {self.order}"


class ProductVariant(models.Model):
    """Product variants (size, color, etc.)"""
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='variants',
        verbose_name="Product"
    )
    name = models.CharField(max_length=100, verbose_name="Variant Name (e.g., Red, XL)")
    sku = models.CharField(max_length=100, unique=True, verbose_name="SKU")
    price = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Price")
    compare_price = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0, verbose_name="Stock")
    is_default = models.BooleanField(default=False, verbose_name="Default Variant")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Product Variant"
        verbose_name_plural = "Product Variants"
        unique_together = ['product', 'sku']

    def __str__(self):
        return f"{self.product.name} - {self.name}"
    
    @property
    def final_price(self):
        return self.compare_price if self.compare_price else self.price


class Attribute(models.Model):
    """Product attributes (e.g., RAM, Processor, Color)"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    is_filterable = models.BooleanField(default=True, help_text="Can be used for filtering")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Attribute"
        verbose_name_plural = "Attributes"
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class AttributeValue(models.Model):
    """Attribute values (e.g., 8GB, 16GB, Red, Blue)"""
    attribute = models.ForeignKey(Attribute, on_delete=models.CASCADE, related_name='values')
    value = models.CharField(max_length=100)
    slug = models.SlugField()

    class Meta:
        verbose_name = "Attribute Value"
        verbose_name_plural = "Attribute Values"
        unique_together = ['attribute', 'value']
        ordering = ['value']

    def __str__(self):
        return f"{self.attribute.name}: {self.value}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.value)
        super().save(*args, **kwargs)


class ProductAttribute(models.Model):
    """Product attributes mapping"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='product_attributes')
    attribute_value = models.ForeignKey(AttributeValue, on_delete=models.CASCADE)
    extra_value = models.CharField(max_length=255, blank=True, help_text="For custom values")

    class Meta:
        verbose_name = "Product Attribute"
        verbose_name_plural = "Product Attributes"
        unique_together = ['product', 'attribute_value']

    def __str__(self):
        return f"{self.product.name} - {self.attribute_value}"


class Tag(models.Model):
    """Product tags for better search"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tag"
        verbose_name_plural = "Tags"
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class ProductTag(models.Model):
    """Product-Tag mapping"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='product_tags')
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name='tag_products')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Product Tag"
        verbose_name_plural = "Product Tags"
        unique_together = ['product', 'tag']

    def __str__(self):
        return f"{self.product.name} - {self.tag.name}"
    
class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=200, blank=True)
    comment = models.TextField()
    is_approved = models.BooleanField(default=False)
    helpful_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['product', 'user']
        ordering = ['-created_at']
        
class Wishlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='wishlisted_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'product']
        ordering = ['-created_at']
        
class RecentlyViewed(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recently_viewed')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-viewed_at']
        unique_together = ['user', 'product']