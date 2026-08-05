from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Create or update periodic Celery Beat tasks for observability."

    def handle(self, *args, **options):
        interval, _created = IntervalSchedule.objects.get_or_create(
            every=5,
            period=IntervalSchedule.MINUTES,
        )

        task, created = PeriodicTask.objects.update_or_create(
            name="Collect observability health snapshot",
            defaults={
                "interval": interval,
                "task": "apps.observability.tasks.collect_observability_health_snapshot",
                "enabled": True,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    "Observability health snapshot task created successfully."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Observability health snapshot task updated successfully."
                )
            )

        self.stdout.write(f"Task: {task.task}")
        self.stdout.write("Interval: every 5 minutes")