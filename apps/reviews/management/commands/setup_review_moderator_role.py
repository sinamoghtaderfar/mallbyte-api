from django.core.management.base import BaseCommand

from apps.reviews.admin_roles import get_or_create_review_moderators_group


class Command(BaseCommand):
    help = "Create or update the Review Moderators admin group."

    def handle(self, *args, **options):
        group = get_or_create_review_moderators_group()

        self.stdout.write(
            self.style.SUCCESS(
                f"Review moderator group is ready: {group.name}"
            )
        )
