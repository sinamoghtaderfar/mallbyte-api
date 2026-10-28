"""Idempotent Celery Beat health and cleanup scheduling."""
import json
from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Configure periodic health collection and safe retention cleanup."

    def handle(self, *args, **options):
        health_interval, _ = IntervalSchedule.objects.get_or_create(
            every=5, period=IntervalSchedule.MINUTES,
        )
        health, _ = PeriodicTask.objects.update_or_create(
            name="Collect observability health snapshot",
            defaults={
                "interval": health_interval,
                "task": "apps.observability.tasks.collect_observability_health_snapshot",
                "args": "[]", "enabled": True,
            },
        )
        cleanup_interval, _ = IntervalSchedule.objects.get_or_create(
            every=24, period=IntervalSchedule.HOURS,
        )
        cleanup, _ = PeriodicTask.objects.update_or_create(
            name="Clean up observability logs",
            defaults={
                "interval": cleanup_interval,
                "task": "apps.observability.tasks.cleanup_observability_logs",
                "args": json.dumps([]), "enabled": True,
            },
        )
        self.stdout.write(self.style.SUCCESS("Observability schedules configured."))
        self.stdout.write(f"Task: {health.task}")
        self.stdout.write("Interval: every 5 minutes")
        self.stdout.write(f"Task: {cleanup.task} (every 24 hours)")
