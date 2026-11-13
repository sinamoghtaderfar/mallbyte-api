import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0004_remove_stocktransfer_delivered_at_and_more")]

    operations = [
        migrations.AlterField(
            model_name=model_name,
            name=field_name,
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name=related_name,
                to="inventory.warehouse",
                verbose_name=verbose_name,
            ),
        )
        for model_name, field_name, related_name, verbose_name in [
            ("stock", "warehouse", "stock_items", "Warehouse"),
            ("stockmovement", "warehouse", "stock_movements", "Warehouse"),
            ("stocktransfer", "from_warehouse", "transfers_out", "From Warehouse"),
            ("stocktransfer", "to_warehouse", "transfers_in", "To Warehouse"),
        ]
    ]
