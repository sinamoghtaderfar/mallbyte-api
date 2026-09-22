from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="payment",
            constraint=models.UniqueConstraint(
                fields=["order"],
                condition=models.Q(status="success"),
                name="unique_successful_payment_per_order",
            ),
        ),
    ]
