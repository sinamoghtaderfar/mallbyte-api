from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Avg, Count, Q

from apps.products.models import Product
from apps.reviews.models import ProductReview, ProductReviewVote


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


def update_review_vote_counts(review: ProductReview):
    stats = ProductReviewVote.objects.filter(review=review).aggregate(
        helpful_count=Count(
            "id",
            filter=Q(vote=ProductReviewVote.VoteChoices.HELPFUL),
        ),
        not_helpful_count=Count(
            "id",
            filter=Q(vote=ProductReviewVote.VoteChoices.NOT_HELPFUL),
        ),
    )

    review.helpful_count = stats["helpful_count"] or 0
    review.not_helpful_count = stats["not_helpful_count"] or 0

    review.save(
        update_fields=[
            "helpful_count",
            "not_helpful_count",
            "updated_at",
        ]
    )

    return review


def set_review_vote(*, review: ProductReview, user, vote):
    if review.status != ProductReview.StatusChoices.APPROVED:
        raise ValueError("You can only vote on approved reviews.")

    if review.customer_id == user.id:
        raise ValueError("You cannot vote on your own review.")

    if vote not in ProductReviewVote.VoteChoices.values:
        raise ValueError("Invalid review vote.")

    with transaction.atomic():
        locked_review = ProductReview.objects.select_for_update().get(pk=review.pk)

        review_vote, _ = ProductReviewVote.objects.update_or_create(
            review=locked_review,
            user=user,
            defaults={
                "vote": vote,
            },
        )

        update_review_vote_counts(locked_review)

    return review_vote, locked_review