"""Financial posting operations. Do not call refund/payout functions from public input.

Trust boundaries:
  * build_order_allocations: after checkout's final totals are persisted.
  * post_captured_payment: after VERIFIED capture inside payment transaction.
  * post_verified_refund: only after processor confirms actual refund amount.
  * post_confirmed_payout: only after bank/processor confirms actual transfer.
"""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Seller, User
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.returns.models import ReturnRequest
from .models import (
    ConfirmedPayout,
    ConfirmedRefund,
    ItemAllocation,
    RefundAllocation,
    SellerLedgerEntry,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def allocate(total, weights):
    """Largest-remainder allocation, deterministic by original item index."""
    total = money(total)
    weights = [Decimal(str(v)) for v in weights]
    if not weights or any(v < 0 for v in weights) or sum(weights) <= 0:
        if total == 0 and weights:
            return [ZERO] * len(weights)
        raise ValidationError("Cannot allocate over empty/zero/negative merchandise lines.")
    if total < 0:
        raise ValidationError("Negative allocation total.")
    units = int(total / CENT)
    total_weight = sum(weights)
    shares = [(Decimal(units) * w / total_weight) for w in weights]
    base = [int(v.to_integral_value(rounding=ROUND_DOWN)) for v in shares]
    leftover = units - sum(base)
    order = sorted(range(len(weights)), key=lambda i: (-(shares[i] - base[i]), i))
    for i in order[:leftover]:
        base[i] += 1
    return [Decimal(value) * CENT for value in base]


@transaction.atomic
def build_order_allocations(order, *, currency="IRR"):
    """Run ONCE at checkout after discounts and final order totals.

    The contract is: shipping and tax allocated to each item, but reserved for
    the platform. Seller credit = (item gross - discount) - commission.
    Never reconstruct snapshots from CURRENT product ownership later.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    items = list(OrderItem.objects.filter(order_id=order.pk).select_related("product").order_by("pk"))
    if not items:
        raise ValidationError("Cannot create financial allocations for an empty order.")
    if ItemAllocation.objects.filter(order_item__order_id=order.pk).exists():
        raise ValidationError("Order already contains financial snapshots; snapshots are immutable.")
    if money(sum((i.total_price for i in items), ZERO)) != money(order.subtotal):
        raise ValidationError("Item gross does not match order subtotal.")
    if money(order.discount_amount) > money(order.subtotal):
        raise ValidationError("Discount exceeds subtotal.")
    if money(order.total_amount) != money(order.subtotal - order.discount_amount + order.shipping_cost + order.tax_amount):
        raise ValidationError("Order total does not reconcile with components.")
    weights = [money(i.total_price) for i in items]
    discounts = allocate(order.discount_amount, weights)
    shipping = allocate(order.shipping_cost, weights)
    taxes = allocate(order.tax_amount, weights)
    seller_ids = {i.product.seller_id for i in items}
    profiles = Seller.objects.filter(user_id__in=seller_ids)
    rate_by_seller = {p.user_id: p.commission_rate for p in profiles}
    if set(rate_by_seller) != seller_ids:
        raise ValidationError("Every seller must have a commission profile at checkout.")
    created = []
    for idx, item in enumerate(items):
        seller_id = item.product.seller_id
        rate = Decimal(str(rate_by_seller[seller_id]))
        if rate < 0 or rate > 100:
            raise ValidationError("Commission rate must be between 0 and 100.")
        merchandise_net = money(weights[idx] - discounts[idx])
        commission = money(merchandise_net * rate / Decimal("100"))
        obj = ItemAllocation.objects.create(
            order_item=item, seller_id=seller_id, currency=currency.upper(),
            quantity=item.quantity, gross=weights[idx], discount=discounts[idx],
            shipping=shipping[idx], tax=taxes[idx],
            charged=money(merchandise_net + shipping[idx] + taxes[idx]),
            merchandise_net=merchandise_net, commission_rate=rate,
            commission=commission, seller_payable=money(merchandise_net - commission),
        )
        created.append(obj)
    if sum((row.charged for row in created), ZERO) != money(order.total_amount):
        raise ValidationError("Allocations do not reconcile with paid amount.")
    return created


@transaction.atomic
def post_captured_payment(payment):
    """Requires VERIFIED success; safe to replay, not suitable for legacy unsnapshotted orders."""
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status not in (Payment.StatusChoices.SUCCESS, Payment.StatusChoices.REFUNDED) or not payment.paid_at:
        raise ValidationError("Capture has not been verified or paid_at is missing.")
    allocations = list(ItemAllocation.objects.filter(order_item__order_id=order.pk).order_by("pk"))
    if len(allocations) != order.items.count():
        raise ValidationError("Missing order-item financial snapshots; review historical order manually.")
    if money(payment.amount) != money(order.total_amount):
        raise ValidationError("Payment/order mismatch.")
    if any(a.currency != payment.currency.upper() for a in allocations):
        raise ValidationError("Order snapshot currency differs from payment currency.")
    entries = []
    for a in allocations:
        if a.seller_payable == 0:
            continue
        entry, _ = SellerLedgerEntry.objects.get_or_create(
            source_key=f"capture:{payment.pk}:{a.pk}",
            defaults=dict(
                seller_id=a.seller_id, currency=a.currency,
                kind=SellerLedgerEntry.Kind.SALE, amount=a.seller_payable,
                allocation=a, occurred_at=payment.paid_at,
            ),
        )
        entries.append(entry)
    return entries


def seller_balance(seller_id, currency):
    return money(
        SellerLedgerEntry.objects.filter(seller_id=seller_id, currency=currency.upper())
        .aggregate(total=Sum("amount"))["total"] or ZERO
    )


def _refund_replay_matches(existing, payment_id, return_request_id, amount,
                           gateway_reference, currency, lines):
    if (existing.payment_id != payment_id or
            existing.return_request_id != return_request_id or
            existing.amount != amount or
            existing.gateway_reference != gateway_reference or
            existing.currency != currency.upper()):
        return False
    previously = {
        row.allocation.order_item_id: (
            row.customer_merchandise, row.customer_shipping, row.customer_tax
        ) for row in existing.items.select_related("allocation")
    }
    proposed = {
        line["order_item_id"]: (
            money(line.get("merchandise", 0)),
            money(line.get("shipping", 0)),
            money(line.get("tax", 0)),
        ) for line in lines
    }
    return previously == proposed


@transaction.atomic
def post_verified_refund(*, payment_id, return_request_id, confirmed_amount,
                         currency, gateway_reference, idempotency_key, lines,
                         confirmed_at):
    """Call only from trusted verified refund confirmation, never a public API.

    lines: [{"order_item_id": int, "merchandise": str,
             "shipping": str, "tax": str}]
    Refundable shipping/tax is accounted for as PLATFORM liabilities (seller gets
    neither original shipping/tax credits nor a corresponding refund debit).
    """
    if not gateway_reference or not idempotency_key or not confirmed_at or timezone.is_naive(confirmed_at):
        raise ValidationError("Verified reference, idempotency key and aware timestamp required.")
    amount = money(confirmed_amount)
    if amount <= 0:
        raise ValidationError("Refund amount must be positive.")
    existing = ConfirmedRefund.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if not _refund_replay_matches(existing, payment_id, return_request_id, amount, gateway_reference, currency, lines):
            raise ValidationError("Conflicting refund idempotency key.")
        return existing
    # Consistent lock order: Order -> Payment -> Return -> Item allocations -> Seller.
    payment_row = Payment.objects.only("order_id").get(pk=payment_id)
    order = Order.objects.select_for_update().get(pk=payment_row.order_id)
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    request = ReturnRequest.objects.select_for_update().get(pk=return_request_id)
    replay = ConfirmedRefund.objects.filter(idempotency_key=idempotency_key).first()
    if replay:
        if not _refund_replay_matches(replay, payment_id, return_request_id, amount, gateway_reference, currency, lines):
            raise ValidationError("Conflicting refund idempotency key.")
        return replay
    if ConfirmedRefund.objects.filter(payment_id=payment_id, gateway_reference=gateway_reference).exists():
        raise ValidationError("Duplicate processor refund reference.")
    if request.order_id != order.pk or payment.order_id != order.pk:
        raise ValidationError("Refund references a different order.")
    if payment.status not in (Payment.StatusChoices.SUCCESS, Payment.StatusChoices.REFUNDED):
        raise ValidationError("Only captured payments can be refunded.")
    if payment.status == Payment.StatusChoices.REFUNDED and not ConfirmedRefund.objects.filter(payment_id=payment_id).exists():
        raise ValidationError("Legacy refunded payment requires manual reconciliation.")
    if request.status not in (
        ReturnRequest.Status.APPROVED,
        ReturnRequest.Status.ITEM_RECEIVED,
        ReturnRequest.Status.INSPECTING,
        ReturnRequest.Status.REFUND_PENDING,
        ReturnRequest.Status.REFUNDED,
    ):
        raise ValidationError("Return request has not been approved.")
    if currency.upper() != payment.currency.upper():
        raise ValidationError("Refund currency differs from payment currency.")
    if sum((money(x.get("merchandise", 0)) + money(x.get("shipping", 0)) + money(x.get("tax", 0)) for x in lines), ZERO) != amount:
        raise ValidationError("Refund breakdown does not match verified amount.")
    if amount + money(ConfirmedRefund.objects.filter(payment_id=payment_id).aggregate(t=Sum("amount"))["t"] or ZERO) > money(payment.amount):
        raise ValidationError("Refund would exceed captured payment.")
    if not lines or len({x["order_item_id"] for x in lines}) != len(lines):
        raise ValidationError("Unique nonempty item refund breakdown required.")
    existing_items = {
        a.order_item_id: a for a in ItemAllocation.objects.select_for_update()
        .filter(order_item__order_id=order.pk, order_item_id__in=[x["order_item_id"] for x in lines])
    }
    return_items = {
        item.order_item_id: item for item in request.items.select_for_update().all()
    }
    if set(existing_items) != {x["order_item_id"] for x in lines} or not set(existing_items).issubset(return_items):
        raise ValidationError("Refund item does not belong to this approved return.")
    # If status already REFUNDED, only exactly one existing verified refund may
    # be retried with the same idempotency key (handled above).
    if request.status == ReturnRequest.Status.REFUNDED:
        raise ValidationError("This return is already refunded.")
    for a in existing_items.values():
        if a.seller_payable and not SellerLedgerEntry.objects.filter(
            source_key=f"capture:{payment_id}:{a.pk}", kind=SellerLedgerEntry.Kind.SALE,
        ).exists():
            raise ValidationError("Unposted seller capture. Reconcile order before refund.")
    sellers = sorted({a.seller_id for a in existing_items.values()})
    list(User.objects.select_for_update().filter(pk__in=sellers).order_by("pk"))
    refund_lines = []
    for line in lines:
        a = existing_items[line["order_item_id"]]
        merch = money(line.get("merchandise", 0))
        ship = money(line.get("shipping", 0))
        tax = money(line.get("tax", 0))
        if min(merch, ship, tax) < 0 or merch + ship + tax <= 0:
            raise ValidationError("Invalid refund line amounts.")
        prior = RefundAllocation.objects.filter(allocation=a)
        used_merch = money(prior.aggregate(v=Sum("customer_merchandise"))["v"] or ZERO)
        used_shipping = money(prior.aggregate(v=Sum("customer_shipping"))["v"] or ZERO)
        used_tax = money(prior.aggregate(v=Sum("customer_tax"))["v"] or ZERO)
        if merch + used_merch > a.merchandise_net or ship + used_shipping > a.shipping or tax + used_tax > a.tax:
            raise ValidationError("Refund component exceeds originally charged amount.")
        requested = money(return_items[a.order_item_id].approved_refund_amount)
        used_on_return = money(prior.filter(refund__return_request_id=return_request_id).aggregate(v=Sum("customer_amount"))["v"] or ZERO)
        if used_on_return + merch + ship + tax > requested:
            raise ValidationError("Refund exceeds approved return-item amount.")
        # Reversal is proportional to merchandise consideration, never to shipping/tax.
        # Last refund of all merchandise uses remaining credit to prevent rounding drift.
        old_reversed = money(prior.aggregate(v=Sum("seller_reversal"))["v"] or ZERO)
        old_commission = money(prior.aggregate(v=Sum("commission_reversal"))["v"] or ZERO)
        if a.merchandise_net == 0:
            seller_debit, commission_reversal = ZERO, ZERO
        elif used_merch + merch == a.merchandise_net:
            seller_debit = money(a.seller_payable - old_reversed)
            commission_reversal = money(a.commission - old_commission)
        else:
            seller_debit = money(a.seller_payable * merch / a.merchandise_net)
            commission_reversal = money(a.commission * merch / a.merchandise_net)
            seller_debit = min(seller_debit, money(a.seller_payable - old_reversed))
            commission_reversal = min(commission_reversal, money(a.commission - old_commission))
        refund_lines.append((a, merch, ship, tax, seller_debit, commission_reversal))
    refund = ConfirmedRefund.objects.create(
        payment=payment, return_request=request, gateway_reference=gateway_reference,
        idempotency_key=idempotency_key, currency=currency.upper(),
        amount=amount, confirmed_at=confirmed_at,
    )
    for a, merch, ship, tax, seller_debit, commission_reversal in refund_lines:
        RefundAllocation.objects.create(
            refund=refund, allocation=a, customer_amount=money(merch + ship + tax),
            customer_merchandise=merch, customer_shipping=ship, customer_tax=tax,
            seller_reversal=seller_debit, commission_reversal=commission_reversal,
        )
        if seller_debit:
            SellerLedgerEntry.objects.create(
                seller_id=a.seller_id, currency=a.currency,
                kind=SellerLedgerEntry.Kind.REFUND, amount=-seller_debit,
                source_key=f"refund:{refund.pk}:{a.pk}", allocation=a,
                refund=refund, occurred_at=confirmed_at,
            )
    total_refunded = money(ConfirmedRefund.objects.filter(payment=payment).aggregate(v=Sum("amount"))["v"] or ZERO)
    if total_refunded == money(payment.amount):
        payment.status = Payment.StatusChoices.REFUNDED
        payment.refunded_at = confirmed_at
        payment.save(update_fields=["status", "refunded_at", "updated_at"])
    return refund


@transaction.atomic
def post_confirmed_payout(*, seller_id, currency, amount, external_reference, idempotency_key, confirmed_at):
    """Proof of completed disbursement. No money is sent by this function."""
    if not external_reference or not idempotency_key or not confirmed_at or timezone.is_naive(confirmed_at):
        raise ValidationError("External reference, idempotency key and aware timestamp required.")
    amount = money(amount)
    if amount <= 0:
        raise ValidationError("Payout amount must be positive.")
    existing = ConfirmedPayout.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.seller_id != seller_id or existing.currency != currency.upper() or existing.amount != amount or existing.external_reference != external_reference:
            raise ValidationError("Conflicting payout idempotency key.")
        return existing
    User.objects.select_for_update().get(pk=seller_id)
    replay = ConfirmedPayout.objects.filter(idempotency_key=idempotency_key).first()
    if replay:
        if replay.seller_id != seller_id or replay.currency != currency.upper() or replay.amount != amount or replay.external_reference != external_reference:
            raise ValidationError("Conflicting payout idempotency key.")
        return replay
    if ConfirmedPayout.objects.filter(external_reference=external_reference).exists():
        raise ValidationError("Duplicate external payout reference.")
    if getattr(settings, "SETTLEMENTS_LEDGER_ENABLED", False):
        from apps.settlements.settlement_policy import payout_eligibility
        eligible = payout_eligibility(seller_id, currency)
        if Decimal(eligible["withdrawable_amount"]) < amount:
            raise ValidationError(
                "Payout exceeds eligible released balance. Reconcile with bank before posting."
            )
    if seller_balance(seller_id, currency) < amount:
        # A transfer might already have occurred externally. Never silently ignore
        # it; it needs manual reconciliation before recording.
        raise ValidationError("Payout exceeds seller ledger balance; reconcile externally.")
    payout = ConfirmedPayout.objects.create(
        seller_id=seller_id, currency=currency.upper(), amount=amount,
        external_reference=external_reference, idempotency_key=idempotency_key,
        confirmed_at=confirmed_at,
    )
    SellerLedgerEntry.objects.create(
        seller_id=seller_id, currency=currency.upper(),
        kind=SellerLedgerEntry.Kind.PAYOUT, amount=-amount,
        source_key=f"payout:{payout.pk}", occurred_at=confirmed_at,
    )
    return payout
