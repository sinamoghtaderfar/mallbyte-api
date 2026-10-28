"""Only one unresolved (open/acknowledged) alert per nonempty fingerprint."""
from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def deduplicate_existing_active_alerts(apps, schema_editor):
    Alert = apps.get_model("observability", "ObservabilityAlert")
    # Keep oldest live alert so existing references/acknowledgements remain stable.
    fingerprints = (
        Alert.objects.filter(status__in=["open", "acknowledged"])
        .exclude(fingerprint="").values_list("fingerprint", flat=True).distinct()
    )
    now = timezone.now()
    for fingerprint in fingerprints:
        active = list(Alert.objects.filter(
            fingerprint=fingerprint, status__in=["open", "acknowledged"],
        ).order_by("created_at", "pk").values_list("pk", flat=True))
        if len(active) > 1:
            Alert.objects.filter(pk__in=active[1:]).update(
                status="resolved", resolved_at=now, updated_at=now,
            )


class Migration(migrations.Migration):
    dependencies = [("observability", "0001_initial")]
    operations = [
        migrations.RunPython(deduplicate_existing_active_alerts, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="observabilityalert",
            constraint=models.UniqueConstraint(
                fields=["fingerprint"],
                condition=Q(status__in=["open", "acknowledged"]) & ~Q(fingerprint=""),
                name="obs_one_live_fingerprint",
            ),
        ),
    ]
