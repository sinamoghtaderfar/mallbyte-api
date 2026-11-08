from django.db import migrations, models

import apps.analytics.models
import apps.support.storage


class Migration(migrations.Migration):
    dependencies = [("analytics", "0001_initial")]

    operations = [migrations.AlterField(
        model_name="analyticsgeneratedreport", name="file",
        field=models.FileField(blank=True, null=True, upload_to=apps.analytics.models.analytics_report_upload_path,
                               storage=apps.support.storage.PrivateMediaStorage()),
    )]
