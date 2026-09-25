import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "orders",
            "0002_sellerorderfulfillment_sellerorderfulfillmenthistory_and_more",
        ),
        ("shipping", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="shipment",
            name="seller_fulfillment",
            field=models.ForeignKey(
                to="orders.sellerorderfulfillment",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="shipments",
                null=True,
                blank=True,
            ),
        ),
        migrations.AddIndex(
            model_name="shipment",
            index=models.Index(
                fields=["seller_fulfillment", "status"],
                name="shipping_sh_seller__1924a6_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="shipment",
            constraint=models.UniqueConstraint(
                fields=["seller_fulfillment"],
                condition=(
                    models.Q(seller_fulfillment__isnull=False)
                    & ~models.Q(status__in=["cancelled", "returned"])
                ),
                name="unique_active_shipment_per_seller_order",
            ),
        ),
    ]
