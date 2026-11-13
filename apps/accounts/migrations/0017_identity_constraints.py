from django.db import migrations, models
from django.db.models.functions import Lower, Trim


def prepare_identity_constraints(apps, schema_editor):
    user = apps.get_model("accounts", "User")
    users = user._base_manager.using(schema_editor.connection.alias)
    duplicates = users.annotate(normalized=Lower(Trim("email"))).values("normalized").annotate(total=models.Count("pk")).filter(total__gt=1)
    if duplicates.exists():
        raise RuntimeError("Resolve duplicate normalized account emails before applying identity constraints; no identities were modified.")
    users.update(email=Lower(Trim("email")))
    # Challenges are short-lived and must be reissued after this rollout.
    apps.get_model("accounts", "OTP").objects.using(schema_editor.connection.alias).filter(is_used=False).update(is_used=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0016_user_auth_version")]
    operations = [
        migrations.RunPython(prepare_identity_constraints, migrations.RunPython.noop),
        migrations.AddConstraint(model_name="user", constraint=models.UniqueConstraint(Lower("email"), name="accounts_user_email_case_insensitive_unique")),
        migrations.AddConstraint(model_name="otp", constraint=models.UniqueConstraint(fields=("email",), condition=models.Q(is_used=False), name="accounts_otp_one_unused_per_email")),
    ]
