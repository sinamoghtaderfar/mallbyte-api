"""Immutable financial snapshots and append-only settlement evidence.

These models deliberately do not connect to a payment processor. Only trusted,
verified integrations should call the money-posting services.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q


class ItemAllocation(models.Model):
    order_item = models.OneToOneField(
        "orders.OrderItem",
        on_delete=models.PROTECT,
        related_name="financial_allocation",
    )
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    currency = models.CharField(max_length=10, default="IRR")
    quantity = models.PositiveIntegerField()
    gross = models.DecimalField(max_digits=18, decimal_places=2)
    discount = models.DecimalField(max_digits=18, decimal_places=2)
    shipping = models.DecimalField(max_digits=18, decimal_places=2)
    tax = models.DecimalField(max_digits=18, decimal_places=2)
    charged = models.DecimalField(max_digits=18, decimal_places=2)
    merchandise_net = models.DecimalField(max_digits=18, decimal_places=2)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2)
    commission = models.DecimalField(max_digits=18, decimal_places=2)
    seller_payable = models.DecimalField(max_digits=18, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    id = models.BigAutoField(primary_key=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["seller", "currency"], name="settle_all_seller_currency_idx"
            )
        ]


class ConfirmedRefund(models.Model):
    """One *externally verified* refund transaction (may be partial)."""

    payment = models.ForeignKey(
        "payments.Payment", on_delete=models.PROTECT, related_name="settlement_refunds"
    )
    return_request = models.ForeignKey(
        "returns.ReturnRequest",
        on_delete=models.PROTECT,
        related_name="confirmed_financial_refunds",
    )
    gateway_reference = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=160, unique=True)
    currency = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    confirmed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    id = models.BigAutoField(primary_key=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "gateway_reference"],
                name="unique_verified_refund_reference",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="positive_confirmed_refund"
            ),
        ]


class RefundAllocation(models.Model):
    refund = models.ForeignKey(
        ConfirmedRefund, on_delete=models.PROTECT, related_name="items"
    )
    allocation = models.ForeignKey(
        ItemAllocation, on_delete=models.PROTECT, related_name="refund_allocations"
    )
    customer_amount = models.DecimalField(max_digits=18, decimal_places=2)
    customer_merchandise = models.DecimalField(max_digits=18, decimal_places=2)
    customer_shipping = models.DecimalField(max_digits=18, decimal_places=2)
    customer_tax = models.DecimalField(max_digits=18, decimal_places=2)
    seller_reversal = models.DecimalField(max_digits=18, decimal_places=2)
    commission_reversal = models.DecimalField(max_digits=18, decimal_places=2)
    id = models.BigAutoField(primary_key=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["refund", "allocation"], name="unique_refund_allocation_item"
            ),
            models.CheckConstraint(
                condition=Q(customer_amount__gt=0), name="positive_refund_allocation"
            ),
        ]


class SellerLedgerEntry(models.Model):
    class Kind(models.TextChoices):
        SALE = "sale", "Sale credit"
        REFUND = "refund", "Refund debit"
        PAYOUT = "payout", "Confirmed payout debit"

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="settlement_ledger",
    )
    currency = models.CharField(max_length=10)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    source_key = models.CharField(max_length=180, unique=True)
    allocation = models.ForeignKey(
        ItemAllocation, on_delete=models.PROTECT, null=True, blank=True
    )
    refund = models.ForeignKey(
        ConfirmedRefund, on_delete=models.PROTECT, null=True, blank=True
    )
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    id = models.BigAutoField(primary_key=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["seller", "currency", "occurred_at"],
                name="settle_seller_curr_time_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(amount=0), name="nonzero_seller_ledger_entry"
            )
        ]


class ConfirmedPayout(models.Model):
    """Proof of an already-executed bank/processor transfer; never initiates one."""

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_payouts",
    )
    currency = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    external_reference = models.CharField(max_length=255, unique=True)
    idempotency_key = models.CharField(max_length=160, unique=True)
    confirmed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    id = models.BigAutoField(primary_key=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="positive_confirmed_payout"
            )
        ]

from .monitoring_models import FinancialAuditRun, FinancialAuditAlert  # noqa: E402,F401
