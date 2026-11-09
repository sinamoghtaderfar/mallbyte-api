import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0003_backfill_seller_fulfillments"),
        ("inventory", "0005_protect_warehouse_history"),
    ]

    operations = [
        migrations.AlterField(
            model_name="orderitem",
            name="warehouse",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="order_items",
                to="inventory.warehouse",
            ),
        ),
    ]
