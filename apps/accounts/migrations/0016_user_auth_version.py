from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0015_admin_mfa")]
    operations = [
        migrations.AddField(
            model_name="user",
            name="auth_version",
            field=models.PositiveIntegerField(default=1, editable=False),
        ),
    ]
