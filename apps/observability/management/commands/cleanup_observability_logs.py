from django.core.management.base import BaseCommand

from apps.observability.services import cleanup_old_observability_logs


class Command(BaseCommand):
    help = "Delete old observability logs and health snapshots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Delete logs older than this number of days.",
        )

    def handle(self, *args, **options):
        days = options["days"]

        result = cleanup_old_observability_logs(days=days)

        self.stdout.write(
            self.style.SUCCESS(
                f"Observability cleanup completed for logs older than {days} days."
            )
        )

        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")