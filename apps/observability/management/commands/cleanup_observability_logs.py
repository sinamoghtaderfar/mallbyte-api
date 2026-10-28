"""One-time cleanup with separate audit-log retention policy."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.observability.services import cleanup_old_observability_logs


class Command(BaseCommand):
    help = "Delete old operational records; audit retention is configured separately."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--audit-days", type=int, default=None)

    def handle(self, *args, **options):
        days = options["days"] if options["days"] is not None else getattr(settings, "OBSERVABILITY_LOG_RETENTION_DAYS", 30)
        audit_days = options["audit_days"] if options["audit_days"] is not None else getattr(settings, "OBSERVABILITY_AUDIT_RETENTION_DAYS", 365)
        if days < 1 or audit_days < 1:
            raise CommandError("Retention days must be positive")
        result = cleanup_old_observability_logs(days=days, audit_days=audit_days)
        self.stdout.write(self.style.SUCCESS("Observability cleanup completed."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
