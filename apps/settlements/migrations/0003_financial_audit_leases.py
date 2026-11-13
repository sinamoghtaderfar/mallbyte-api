import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("settlements", "0002_financial_audit_monitoring")]
    operations = [
        migrations.AddField("financialauditrun", "attempts", models.PositiveSmallIntegerField(default=0)),
        migrations.AddField("financialauditrun", "sample_limit", models.PositiveSmallIntegerField(default=20)),
        migrations.AddField("financialauditrun", "started_at", models.DateTimeField(null=True, blank=True)),
        migrations.AddField("financialauditrun", "execution_token", models.UUIDField(default=uuid.uuid4, editable=False)),
    ]
