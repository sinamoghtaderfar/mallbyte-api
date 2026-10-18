import csv
from decimal import Decimal

from django.db.models import Count, Sum
from django.http import StreamingHttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.permissions import CanViewSellerAnalytics, CanViewPlatformAnalytics
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.returns.models import ReturnRequest
from .models import ItemAllocation, ConfirmedRefund, SellerLedgerEntry


def _safe_csv(value):
    text = str(value if value is not None else "")
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + text
    return text


def statement(seller_id):
    """No user/client-supplied seller_id is used by API callers."""
    rows = (SellerLedgerEntry.objects.filter(seller_id=seller_id)
            .values("currency", "kind")
            .annotate(amount=Sum("amount"), count=Count("id"))
            .order_by("currency", "kind"))
    currencies = {}
    for row in rows:
        c = currencies.setdefault(row["currency"], {"currency": row["currency"], "sales": Decimal(0), "refunds": Decimal(0), "payouts": Decimal(0), "balance": Decimal(0)})
        value = row["amount"] or Decimal(0)
        c[{"sale": "sales", "refund": "refunds", "payout": "payouts"}[row["kind"]]] += value
        c["balance"] += value
    totals = []
    for c in currencies.values():
        totals.append({key: (str(v.quantize(Decimal("0.01"))) if isinstance(v, Decimal) else v) for key, v in c.items()})
    recent = list(SellerLedgerEntry.objects.filter(seller_id=seller_id)
                  .order_by("-occurred_at", "-pk")
                  .values("kind", "currency", "amount", "occurred_at")[:100])
    for e in recent:
        e["amount"] = str(e["amount"])
    return {
        "scope": "authenticated_seller",
        "currencies": sorted(totals, key=lambda x: x["currency"]),
        "recent_entries": recent,
        "notice": "Seller merchandise settlement ledger; shipping and taxes belong to the platform by the current policy.",
    }


class SellerStatementView(APIView):
    permission_classes = [IsAuthenticated, CanViewSellerAnalytics]

    def get(self, request):
        return Response(statement(request.user.pk))


class _CSVBuffer:
    def write(self, data):
        return data


class SellerStatementCSVView(APIView):
    permission_classes = [IsAuthenticated, CanViewSellerAnalytics]

    def get(self, request):
        queryset = (SellerLedgerEntry.objects.filter(seller_id=request.user.pk)
                    .order_by("occurred_at", "pk")
                    .values_list("occurred_at", "kind", "currency", "amount"))
        writer = csv.writer(_CSVBuffer())

        def rows():
            yield "\ufeff" + writer.writerow(["date", "kind", "currency", "amount"])
            for item in queryset.iterator(chunk_size=1000):
                yield writer.writerow([_safe_csv(v) for v in item])

        response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="seller_statement.csv"'
        return response


class SettlementAlertsView(APIView):
    permission_classes = [IsAuthenticated, CanViewPlatformAnalytics]

    def get(self, request):
        # Security: aggregated operational metrics, no customer/bank details.
        paid_unallocated = Order.objects.filter(
            payment_status=Order.PaymentStatusChoices.PAID,
            items__financial_allocation__isnull=True,
        ).distinct().count()
        negative_sellers = list(
            SellerLedgerEntry.objects.values("seller_id", "currency")
            .annotate(balance=Sum("amount")).filter(balance__lt=0)
            .values("seller_id", "currency", "balance")[:100]
        )
        return Response({
            "paid_orders_missing_item_snapshots": paid_unallocated,
            "seller_balances_below_zero": [
                {"seller_id": r["seller_id"], "currency": r["currency"], "balance": str(r["balance"])}
                for r in negative_sellers
            ],
            "legacy_refunded_payments_without_verified_refund": Payment.objects.filter(
                status=Payment.StatusChoices.REFUNDED,
                settlement_refunds__isnull=True,
            ).count(),
            "returns_marked_refunded_without_verified_payment": ReturnRequest.objects.filter(
                status=ReturnRequest.Status.REFUNDED,
                confirmed_financial_refunds__isnull=True,
            ).count(),
            "approved_returns_waiting_for_confirmed_refund": ReturnRequest.objects.filter(
                status=ReturnRequest.Status.APPROVED,
                confirmed_financial_refunds__isnull=True,
            ).count(),
            "confirmed_refund_events": ConfirmedRefund.objects.count(),
        })
