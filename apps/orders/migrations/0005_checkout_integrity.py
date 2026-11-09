from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("orders", "0004_protect_order_warehouse")]

    operations = [
        migrations.AddField(
            model_name="order", name="checkout_key",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="order", name="checkout_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="order", name="reservation_expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(
                fields=["user", "checkout_key"], condition=~models.Q(checkout_key=""),
                name="unique_checkout_key_per_user",
            ),
        ),
    ]
