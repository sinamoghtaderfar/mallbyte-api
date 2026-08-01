from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Avg, Count

from apps.products.models import Product
from apps.reviews.models import ProductReview


def normalize_average_rating(value):
    if value is None:
        return Decimal("0.00")

    return Decimal(str(value)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def update_product_review_stats(product: Product):
    stats = ProductReview.objects.filter(
        product=product,
        status=ProductReview.StatusChoices.APPROVED,
    ).aggregate(
        average_rating=Avg("rating"),
        reviews_count=Count("id"),
    )

    product.avrage_rating = normalize_average_rating(stats["average_rating"])
    product.reviews_count = stats["reviews_count"] or 0

    product.save(
        update_fields=[
            "avrage_rating",
            "reviews_count",
            "updated_at",
        ]
    )

    return product
