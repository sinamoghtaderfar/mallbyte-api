from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.notifications.services import delete_old_read_notifications


class Command(BaseCommand):
    help = "Delete old read notifications."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Delete read notifications older than this number of days.",
        )

        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="Delete old read notifications only for one user.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        user_id = options["user_id"]

        if days <= 0:
            raise CommandError("days must be greater than zero.")

        user = None

        if user_id is not None:
            User = get_user_model()

            try:
                user = User.objects.get(pk=user_id)
            except User.DoesNotExist as exc:
                raise CommandError(f"User with id {user_id} does not exist.") from exc

        deleted_count = delete_old_read_notifications(
            days=days,
            user=user,
        )

        if user is not None:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {deleted_count} old read notifications for user {user.pk}."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"Deleted {deleted_count} old read notifications.")
        )
