from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("settlements", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="FinancialAuditRun",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("run_key", models.CharField(max_length=96, unique=True)),
                ("source", models.CharField(max_length=12, choices=[("manual", "Manual"), ("scheduled", "Scheduled")])),
                ("status", models.CharField(max_length=12, choices=[("running", "Running"), ("clean", "No findings"), ("warnings", "Warnings"), ("error", "Failed")], default="running")),
                ("findings_count", models.PositiveIntegerField(default=0)),
                ("summary", models.JSONField(default=dict)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(null=True, blank=True)),
            ],
            options={"ordering": ["-created_at", "-pk"], "indexes": [models.Index(fields=["-created_at"], name="sett_audit_run_created_idx")]},
        ),
        migrations.CreateModel(
            name="FinancialAuditAlert",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=100, unique=True)),
                ("is_open", models.BooleanField(default=True)),
                ("findings_count", models.PositiveIntegerField(default=0)),
                ("sample", models.JSONField(default=dict)),
                ("first_seen_at", models.DateTimeField()),
                ("last_seen_at", models.DateTimeField()),
                ("resolved_at", models.DateTimeField(null=True, blank=True)),
                ("last_run", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="alerts", to="settlements.financialauditrun")),
            ],
            options={"ordering": ["-last_seen_at", "code"], "indexes": [models.Index(fields=["is_open", "-last_seen_at"], name="sett_alert_open_seen_idx")]},
        ),
    ]
