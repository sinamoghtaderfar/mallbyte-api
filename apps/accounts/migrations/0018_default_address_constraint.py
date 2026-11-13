from django.db import migrations, models


def check_existing_defaults(apps, schema_editor):
    address = apps.get_model("accounts", "Address")
    duplicates = address.objects.using(schema_editor.connection.alias).filter(is_default=True).values("user_id").annotate(total=models.Count("pk")).filter(total__gt=1)
    if duplicates.exists():
        raise RuntimeError("Review duplicate default addresses and explicitly choose one per user before applying this migration; no addresses were modified.")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0017_identity_constraints")]
    operations = [
        migrations.RunPython(check_existing_defaults, migrations.RunPython.noop),
        migrations.AddConstraint(model_name="address", constraint=models.UniqueConstraint(fields=("user",), condition=models.Q(is_default=True), name="accounts_one_default_address_per_user")),
    ]
