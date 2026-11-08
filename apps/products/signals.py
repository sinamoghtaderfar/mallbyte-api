"""Post-commit product assets; inventory owns low-stock notifications."""
import logging
from functools import partial

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Product
from .utils import generate_product_qr_code

logger = logging.getLogger(__name__)


def generate_missing_qr_code(product_id):
    try:
        with transaction.atomic():
            product = Product.objects.select_for_update().filter(pk=product_id, qr_code="").first()
            if product is None:
                return
            generate_product_qr_code(product)
            Product.objects.filter(pk=product.pk).update(qr_code=product.qr_code.name)
    except Exception as exc:
        logger.warning("Product QR generation failed for id=%s (%s)", product_id, type(exc).__name__)


@receiver(post_save, sender=Product, dispatch_uid="products.generate_qr_after_commit")
def generate_qr_code(sender, instance, created, **kwargs):
    if created and not instance.qr_code:
        transaction.on_commit(partial(generate_missing_qr_code, instance.pk))
