"""Opt-in setup: python manage.py install_financial_audit_schedule --hour 3."""
from django.conf import settings
from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Install or update a daily financial reconciliation Celery Beat schedule."

    def add_arguments(self, parser):
        parser.add_argument("--hour", type=int, default=3)
        parser.add_argument("--minute", type=int, default=0)
        parser.add_argument("--disable", action="store_true")

    def handle(self, *args, **options):
        h, m = options["hour"], options["minute"]
        if not 0 <= h <= 23 or not 0 <= m <= 59:
            raise ValueError("Hour/minute must form a valid 24-hour time.")
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=str(m), hour=str(h), day_of_week="*", day_of_month="*",
            month_of_year="*", timezone=settings.TIME_ZONE,
        )
        task, _ = PeriodicTask.objects.update_or_create(
            name="MallByte financial reconciliation daily",
            defaults={
                "task": "apps.settlements.tasks.run_daily_financial_audit",
                "crontab": schedule,
                "interval": None,
                "solar": None,
                "clocked": None,
                "enabled": not options["disable"],
                "args": "[]", "kwargs": "{}",
            },
        )
        self.stdout.write(self.style.SUCCESS(
            f"Scheduled audit: {'enabled' if task.enabled else 'disabled'} at {h:02}:{m:02} {settings.TIME_ZONE}"
        ))
