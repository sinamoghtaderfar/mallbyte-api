from django.db import migrations, models

import apps.support.models
import apps.support.storage


class Migration(migrations.Migration):
    dependencies = [("support", "0003_alter_ticketauditlog_action")]

    operations = [
        migrations.AlterField(
            model_name="ticketattachment",
            name="file",
            field=models.FileField(
                storage=apps.support.storage.SupportAttachmentStorage(),
                upload_to=apps.support.models.support_attachment_path,
            ),
        ),
    ]
