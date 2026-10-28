"""Incident management, AI suggestions and approved operations."""
import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import apps.observability.workflow_models


class Migration(migrations.Migration):
    dependencies = [
        ("observability", "0002_unique_active_alert_fingerprint"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="Incident",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("severity", models.CharField(max_length=12, db_index=True, default="medium", choices=[("low","Low"),("medium","Medium"),("high","High"),("critical","Critical")])),
                ("status", models.CharField(max_length=20, db_index=True, default="open", choices=[("open","Open"),("investigating","Investigating"),("mitigated","Mitigated"),("resolved","Resolved"),("closed","Closed")])),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_observability_incidents", to=settings.AUTH_USER_MODEL)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_observability_incidents", to=settings.AUTH_USER_MODEL)),
                ("source_error", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="incidents", to="observability.errorlog")),
                ("source_alert", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="incidents", to="observability.observabilityalert")),
            ], options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="IncidentEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_type", models.CharField(max_length=16, choices=[("created","Created"),("assigned","Assigned"),("status","Status change"),("comment","Comment"),("ai","AI diagnosis")])),
                ("note", models.TextField(blank=True)),
                ("from_value", models.CharField(blank=True, max_length=120)),
                ("to_value", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="observability_incident_events", to=settings.AUTH_USER_MODEL)),
                ("incident", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="observability.incident")),
            ], options={"ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="AIDiagnosis",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("model_name", models.CharField(max_length=100)),
                ("response", models.TextField(blank=True)),
                ("status", models.CharField(max_length=12, db_index=True, default="queued", choices=[("queued","Queued"),("running","Running"),("succeeded","Succeeded"),("failed","Failed")])),
                ("include_description", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("incident", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="diagnoses", to="observability.incident")),
                ("requested_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requested_observability_diagnoses", to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="InfrastructureOperation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("target", models.CharField(max_length=24, choices=[("celery_worker","Celery Worker"),("celery_beat","Celery Beat"),("redis","Redis")])),
                ("status", models.CharField(max_length=16, db_index=True, default="pending", choices=[("pending","Pending approval"),("approved","Approved"),("rejected","Rejected"),("cancelled","Cancelled"),("running","Running"),("succeeded","Succeeded"),("failed","Failed"),("expired","Expired")])),
                ("reason", models.TextField()),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(default=apps.observability.workflow_models.operation_expiry)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("result_message", models.CharField(blank=True, max_length=500)),
                ("execution_token_hash", models.CharField(blank=True, editable=False, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("requested_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requested_observability_operations", to=settings.AUTH_USER_MODEL)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_observability_operations", to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ["-created_at"]},
        ),
    ]
