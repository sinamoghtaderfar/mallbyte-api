from decimal import ROUND_HALF_UP, Decimal

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

def get_product_review_summary(product: Product):
    approved_reviews = ProductReview.objects.filter(
        product=product,
        status=ProductReview.StatusChoices.APPROVED,
    )

    rating_counts = approved_reviews.aggregate(
        five_star=Count("id", filter=Q(rating=5)),
        four_star=Count("id", filter=Q(rating=4)),
        three_star=Count("id", filter=Q(rating=3)),
        two_star=Count("id", filter=Q(rating=2)),
        one_star=Count("id", filter=Q(rating=1)),
    )

    total_count = approved_reviews.count()

    return {
        "product_id": product.pk,
        "average_rating": str(product.avrage_rating),
        "reviews_count": product.reviews_count,
        "rating_breakdown": {
            "5": rating_counts["five_star"] or 0,
            "4": rating_counts["four_star"] or 0,
            "3": rating_counts["three_star"] or 0,
            "2": rating_counts["two_star"] or 0,
            "1": rating_counts["one_star"] or 0,
        },
        "total_approved_reviews": total_count,
    }