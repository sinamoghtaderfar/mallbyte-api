# apps/products/signals.py

from django.conf import settings
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Product, RecentlyViewed
from .utils import generate_product_qr_code


def add_product_to_recently_viewed(user, product):
    """Add a product to user's recently viewed list."""
    if not user.is_authenticated:
        return

    RecentlyViewed.objects.filter(user=user, product=product).delete()

    RecentlyViewed.objects.create(user=user, product=product)

    recent_count = RecentlyViewed.objects.filter(user=user).count()

    if recent_count > 20:
        oldest = RecentlyViewed.objects.filter(user=user).order_by("viewed_at").first()
        if oldest:
            oldest.delete()


@receiver(post_save, sender=Product)
def check_low_stock(sender, instance, **kwargs):
    """
    Check product stock from inventory.Stock.

    Product.stock is no longer a database field.
    Real stock comes from inventory.Stock through:
    instance.available_stock
    """

    available_stock = getattr(instance, "available_stock", 0)

    if 0 < available_stock <= instance.low_stock_threshold:
        seller_email = instance.seller.email

        if seller_email:
            send_mail(
                subject=f"⚠️ Low Stock Alert: {instance.name}",
                message=f"""
Hello {instance.seller.full_name},

Your product "{instance.name}" is running low on stock.

Available stock: {available_stock}
Threshold: {instance.low_stock_threshold}

Please restock soon to avoid losing sales.

Best regards,
MallByte Team
""",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[seller_email],
                fail_silently=True,
            )

            print(f"Low stock alert sent to {seller_email}")


@receiver(post_save, sender=Product)
def generate_qr_code(sender, instance, created, **kwargs):
    """Generate QR code when a product is created."""
    if created and not instance.qr_code:
        generate_product_qr_code(instance)
        Product.objects.filter(pk=instance.pk).update(qr_code=instance.qr_code.name)