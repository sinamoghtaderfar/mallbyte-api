# apps/products/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import RecentlyViewed, Product
from django.utils import timezone


@receiver(post_save, sender=Product)
def add_to_recently_viewed(sender, instance, created, **kwargs):
    """
    This signal is triggered when a product is viewed.
    Note: This is a placeholder. The actual recently viewed
    should be handled in the view using the request.user.
    """
    # this signal is not the best place to handle recently viewed products because it will trigger on every save of a product, not just when a user views it.
    # wenn a product is saved, we don't want to add it to recently viewed. Instead, we should handle this in the view when a user actually views the product.
    pass


def add_product_to_recently_viewed(user, product):
    """Add a product to user's recently viewed list"""
    if not user.is_authenticated:
        return
    
    # delete existing record if exists to avoid duplicates
    RecentlyViewed.objects.filter(user=user, product=product).delete()
    
    # create new record
    RecentlyViewed.objects.create(user=user, product=product)
    
    # keep only the last 20 viewed products
    recent_count = RecentlyViewed.objects.filter(user=user).count()
    if recent_count > 20:
        oldest = RecentlyViewed.objects.filter(user=user).order_by('viewed_at').first()
        if oldest:
            oldest.delete()