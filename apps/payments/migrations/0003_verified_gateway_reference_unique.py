from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_unique_successful_payment"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.UniqueConstraint(
                fields=("provider", "gateway_reference"),
                condition=models.Q(
                    status__in=("success", "refunded"),
                    gateway_reference__gt="",
                ),
                name="unique_provider_verified_capture_reference",
            ),
        ),
    ]
