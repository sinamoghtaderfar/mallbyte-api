# apps/inventory/models.py

from django.db import models
from django.contrib.auth import get_user_model
from apps.products.models import Product

User = get_user_model()


class Warehouse(models.Model):
    """Warehouse model - where products are stored"""
    
    class TypeChoices(models.TextChoices):
        MAIN = 'main', 'Main Warehouse'
        BRANCH = 'branch', 'Branch Warehouse'
        THIRD_PARTY = 'third_party', 'Third Party Warehouse'
    
    name = models.CharField(max_length=100, unique=True, verbose_name="Warehouse Name")
    code = models.CharField(max_length=20, unique=True, verbose_name="Warehouse Code")
    type = models.CharField(max_length=20, choices=TypeChoices.choices, default=TypeChoices.BRANCH)
    
    # Address fields
    province = models.CharField(max_length=50, verbose_name="Province")
    city = models.CharField(max_length=50, verbose_name="City")
    address = models.TextField(verbose_name="Full Address")
    postal_code = models.CharField(max_length=10, verbose_name="Postal Code")
    
    # Contact info
    phone = models.CharField(max_length=15, verbose_name="Phone Number")
    email = models.EmailField(blank=True, verbose_name="Email")
    manager_name = models.CharField(max_length=100, verbose_name="Manager Name")
    manager_phone = models.CharField(max_length=15, verbose_name="Manager Phone")
    
    # Status
    is_active = models.BooleanField(default=True, verbose_name="Is Active")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_warehouses')
    
    class Meta:
        verbose_name = "Warehouse"
        verbose_name_plural = "Warehouses"
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.code})"


class Stock(models.Model):
    """Stock model - tracks product quantity in each warehouse"""
    
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='stock_items',
        verbose_name="Product"
    )
    warehouse = models.ForeignKey(
        Warehouse, 
        on_delete=models.CASCADE, 
        related_name='stock_items',
        verbose_name="Warehouse"
    )
    quantity = models.PositiveIntegerField(default=0, verbose_name="Current Quantity")
    reserved_quantity = models.PositiveIntegerField(default=0, verbose_name="Reserved Quantity")
    low_stock_threshold = models.PositiveIntegerField(default=5, verbose_name="Low Stock Alert Threshold")
    
    # Location within warehouse
    aisle = models.CharField(max_length=20, blank=True, verbose_name="Aisle")
    shelf = models.CharField(max_length=20, blank=True, verbose_name="Shelf")
    bin = models.CharField(max_length=20, blank=True, verbose_name="Bin")
    
    # Timestamps
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='stock_updates')
    
    class Meta:
        verbose_name = "Stock"
        verbose_name_plural = "Stock Items"
        unique_together = ['product', 'warehouse']
    
    def __str__(self):
        return f"{self.product.name} - {self.warehouse.name}: {self.quantity}"
    
    @property
    def available_quantity(self):
        """Available stock = total - reserved"""
        return self.quantity - self.reserved_quantity
    
    @property
    def is_low_stock(self):
        """Check if stock is below threshold"""
        return self.available_quantity <= self.low_stock_threshold


class StockMovement(models.Model):
    """Stock movement history - tracks all inventory changes"""
    
    class MovementType(models.TextChoices):
        PURCHASE = 'purchase', 'Purchase Order'
        SALE = 'sale', 'Customer Order'
        RETURN = 'return', 'Customer Return'
        TRANSFER_IN = 'transfer_in', 'Transfer In'
        TRANSFER_OUT = 'transfer_out', 'Transfer Out'
        ADJUSTMENT = 'adjustment', 'Stock Adjustment'
        DAMAGED = 'damaged', 'Damaged Goods'
    
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_movements')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_movements')
    movement_type = models.CharField(max_length=20, choices=MovementType.choices)
    quantity = models.IntegerField(verbose_name="Quantity (positive = in, negative = out)")
    reference_id = models.CharField(max_length=100, blank=True, help_text="Order ID, Transfer ID, etc.")
    reason = models.TextField(blank=True, verbose_name="Reason for movement")
    
    # Before/after for audit
    before_quantity = models.PositiveIntegerField(default=0)
    after_quantity = models.PositiveIntegerField(default=0)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='stock_movements')
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        verbose_name = "Stock Movement"
        verbose_name_plural = "Stock Movements"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.movement_type}: {self.product.name} x{self.quantity} at {self.warehouse.name}"
    
    def save(self, *args, **kwargs):
        """Auto-calculate before/after quantities"""
        if not self.pk:  # New movement
            try:
                stock = Stock.objects.get(product=self.product, warehouse=self.warehouse)
                self.before_quantity = stock.quantity
            except Stock.DoesNotExist:
                self.before_quantity = 0
            
            # Update stock quantity
            stock, created = Stock.objects.get_or_create(
                product=self.product,
                warehouse=self.warehouse,
                defaults={'quantity': 0}
            )
            stock.quantity += self.quantity
            stock.save()
            
            self.after_quantity = stock.quantity
        
        super().save(*args, **kwargs)


class StockTransfer(models.Model):
    """Stock transfer between warehouses"""
    
    class StatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pending'
        IN_TRANSIT = 'in_transit', 'In Transit'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'
    
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='transfers_out')
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='transfers_in')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.PENDING)
    
    # Tracking
    tracking_number = models.CharField(max_length=100, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    reason = models.TextField(blank=True)
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transfer_requests')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='approved_transfers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Stock Transfer"
        verbose_name_plural = "Stock Transfers"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Transfer {self.product.name}: {self.from_warehouse.name} → {self.to_warehouse.name} ({self.quantity})"