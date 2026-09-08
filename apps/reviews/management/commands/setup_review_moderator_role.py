from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from apps.reviews.models import ProductReview, ProductReviewVote


class Command(BaseCommand):
    help = "Create or update the Review Moderators admin group."

    def handle(self, *args, **options):
        group, created = Group.objects.get_or_create(name="Review Moderators")

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

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} Review Moderators group with limited review permissions."
            )
        )
