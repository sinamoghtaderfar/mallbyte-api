from django.db import migrations, models

import apps.returns.models
import apps.support.storage


class Migration(migrations.Migration):
    dependencies = [("returns", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="returnattachment", name="file",
            field=models.FileField(upload_to=apps.returns.models.return_file_upload_path,
                                   storage=apps.support.storage.PrivateMediaStorage()),
        ),
        migrations.AlterField(
            model_name="returnshipment", name="shipping_label",
            field=models.FileField(blank=True, null=True, upload_to=apps.returns.models.return_file_upload_path,
                                   storage=apps.support.storage.PrivateMediaStorage()),
        ),
    ]
