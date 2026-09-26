"""Backfill missing seller rows on historical paid orders.

Do not infer per-seller delivery from older shipped/delivered orders.
Existing active legacy (unassigned) parcels retain whole-order semantics.
"""
from django.db import migrations


def backfill_missing_seller_fulfillments(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    SellerOrderFulfillment = apps.get_model("orders", "SellerOrderFulfillment")
    Shipment = apps.get_model("shipping", "Shipment")
    alias = schema_editor.connection.alias if schema_editor is not None else "default"

    orders = Order.objects.using(alias).filter(
        payment_status="paid", status__in=["paid", "processing"],
    )
    for order in orders.iterator(chunk_size=250):
        has_active_legacy = (
            Shipment.objects.using(alias)
            .filter(order_id=order.pk, seller_fulfillment_id__isnull=True)
            .exclude(status__in=["cancelled", "returned"])
            .exists()
        )
        if has_active_legacy:
            continue

        seller_ids = set(
            order.items.using(alias)
            .values_list("product__seller_id", flat=True)
            .distinct()
        )
        existing_ids = set(
            SellerOrderFulfillment.objects.using(alias)
            .filter(order_id=order.pk)
            .values_list("seller_id", flat=True)
        )
        # We cannot tell which seller prepared historical processing orders.
        # Missing records start at paid without inventing past transitions.
        SellerOrderFulfillment.objects.using(alias).bulk_create(
            [
                SellerOrderFulfillment(
                    order_id=order.pk, seller_id=seller_id, status="paid",
                )
                for seller_id in sorted(seller_ids - existing_ids)
            ],
            ignore_conflicts=True,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0002_sellerorderfulfillment_sellerorderfulfillmenthistory_and_more"),
        ("shipping", "0002_shipment_seller_fulfillment"),
    ]

    operations = [
        migrations.RunPython(
            backfill_missing_seller_fulfillments,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
