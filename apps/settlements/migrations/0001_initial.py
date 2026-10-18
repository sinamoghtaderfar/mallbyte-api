from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orders", "0003_backfill_seller_fulfillments"),
        ("payments", "0002_unique_successful_payment"),
        ("returns", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="ItemAllocation",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("currency", models.CharField(max_length=10, default="IRR")),
                ("quantity", models.PositiveIntegerField()),
                ("gross", models.DecimalField(max_digits=18, decimal_places=2)),
                ("discount", models.DecimalField(max_digits=18, decimal_places=2)),
                ("shipping", models.DecimalField(max_digits=18, decimal_places=2)),
                ("tax", models.DecimalField(max_digits=18, decimal_places=2)),
                ("charged", models.DecimalField(max_digits=18, decimal_places=2)),
                ("merchandise_net", models.DecimalField(max_digits=18, decimal_places=2)),
                ("commission_rate", models.DecimalField(max_digits=5, decimal_places=2)),
                ("commission", models.DecimalField(max_digits=18, decimal_places=2)),
                ("seller_payable", models.DecimalField(max_digits=18, decimal_places=2)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("seller", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("order_item", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="financial_allocation", to="orders.orderitem")),
            ],
            options={"indexes": [models.Index(fields=["seller", "currency"], name="settle_all_seller_currency_idx")]},
        ),
        migrations.CreateModel(
            name="ConfirmedRefund",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("gateway_reference", models.CharField(max_length=255)),
                ("idempotency_key", models.CharField(max_length=160, unique=True)),
                ("currency", models.CharField(max_length=10)),
                ("amount", models.DecimalField(max_digits=18, decimal_places=2)),
                ("confirmed_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("payment", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="settlement_refunds", to="payments.payment")),
                ("return_request", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="confirmed_financial_refunds", to="returns.returnrequest")),
            ],
        ),
        migrations.CreateModel(
            name="ConfirmedPayout",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("currency", models.CharField(max_length=10)),
                ("amount", models.DecimalField(max_digits=18, decimal_places=2)),
                ("external_reference", models.CharField(max_length=255, unique=True)),
                ("idempotency_key", models.CharField(max_length=160, unique=True)),
                ("confirmed_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("seller", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="confirmed_payouts", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="RefundAllocation",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("customer_amount", models.DecimalField(max_digits=18, decimal_places=2)),
                ("customer_merchandise", models.DecimalField(max_digits=18, decimal_places=2)),
                ("customer_shipping", models.DecimalField(max_digits=18, decimal_places=2)),
                ("customer_tax", models.DecimalField(max_digits=18, decimal_places=2)),
                ("seller_reversal", models.DecimalField(max_digits=18, decimal_places=2)),
                ("commission_reversal", models.DecimalField(max_digits=18, decimal_places=2)),
                ("allocation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="refund_allocations", to="settlements.itemallocation")),
                ("refund", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="items", to="settlements.confirmedrefund")),
            ],
        ),
        migrations.CreateModel(
            name="SellerLedgerEntry",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("currency", models.CharField(max_length=10)),
                ("kind", models.CharField(max_length=12, choices=[("sale", "Sale credit"), ("refund", "Refund debit"), ("payout", "Confirmed payout debit")])),
                ("amount", models.DecimalField(max_digits=18, decimal_places=2)),
                ("source_key", models.CharField(max_length=180, unique=True)),
                ("occurred_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("allocation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, null=True, blank=True, to="settlements.itemallocation")),
                ("refund", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, null=True, blank=True, to="settlements.confirmedrefund")),
                ("seller", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="settlement_ledger", to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes": [models.Index(fields=["seller", "currency", "occurred_at"], name="settle_seller_curr_time_idx")]},
        ),
        migrations.AddConstraint(
            model_name="confirmedrefund",
            constraint=models.UniqueConstraint(fields=["payment", "gateway_reference"], name="unique_verified_refund_reference"),
        ),
        migrations.AddConstraint(
            model_name="confirmedrefund",
            constraint=models.CheckConstraint(condition=models.Q(amount__gt=0), name="positive_confirmed_refund"),
        ),
        migrations.AddConstraint(
            model_name="confirmedpayout",
            constraint=models.CheckConstraint(condition=models.Q(amount__gt=0), name="positive_confirmed_payout"),
        ),
        migrations.AddConstraint(
            model_name="refundallocation",
            constraint=models.UniqueConstraint(fields=["refund", "allocation"], name="unique_refund_allocation_item"),
        ),
        migrations.AddConstraint(
            model_name="refundallocation",
            constraint=models.CheckConstraint(condition=models.Q(customer_amount__gt=0), name="positive_refund_allocation"),
        ),
        migrations.AddConstraint(
            model_name="sellerledgerentry",
            constraint=models.CheckConstraint(condition=~models.Q(amount=0), name="nonzero_seller_ledger_entry"),
        ),
    ]
