from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from apps.reviews.models import ProductReview, ProductReviewVote

REVIEW_MODERATORS_GROUP_NAME = "Review Moderators"


def get_or_create_review_moderators_group():
    group, _ = Group.objects.get_or_create(name=REVIEW_MODERATORS_GROUP_NAME)

    review_content_type = ContentType.objects.get_for_model(ProductReview)
    vote_content_type = ContentType.objects.get_for_model(ProductReviewVote)

    permissions = Permission.objects.filter(
        content_type=review_content_type,
        codename__in=[
            "view_productreview",
            "change_productreview",
        ],
    ) | Permission.objects.filter(
        content_type=vote_content_type,
        codename__in=[
            "view_productreviewvote",
        ],
    )

    group.permissions.set(permissions)

    return group
