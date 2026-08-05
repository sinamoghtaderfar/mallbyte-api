from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Create or update the periodic Celery Beat task for analytics report schedules."

    def handle(self, *args, **options):
        interval, _created = IntervalSchedule.objects.get_or_create(
            every=1,
            period=IntervalSchedule.MINUTES,
        )

        task, created = PeriodicTask.objects.update_or_create(
            name="Run due analytics report schedules",
            defaults={
                "interval": interval,
                "task": "apps.analytics.tasks.run_due_analytics_report_schedules",
                "enabled": True,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    "Analytics report scheduler task created successfully."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Analytics report scheduler task updated successfully."
                )
            )

        self.stdout.write(f"Task: {task.task}")
        self.stdout.write("Interval: every 1 minute")