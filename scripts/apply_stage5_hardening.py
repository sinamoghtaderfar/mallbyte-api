"""One-time LOCAL patch against mallbyte-api main as inspected 2026-10-18.

Do not commit this installer. It fails without writing anything when anchors
have changed. Review diff before running migrations or deploying.
"""
from pathlib import Path

REPLACEMENTS = {}

# Attach immutable order snapshots before checkout transaction commits.
p = "apps/orders/serializers.py"
REPLACEMENTS[p] = [(
    '''from django.core.exceptions import ValidationError as DjangoValidationError''',
    '''from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError''',
), (
    '''            OrderStatusHistory.objects.create(
                order=order,
                old_status="",
                new_status=order.status,
                changed_by=user,
                note="Order created from cart.",
            )''',
    '''            if getattr(settings, "SETTLEMENTS_LEDGER_ENABLED", False):
                from apps.settlements.services import build_order_allocations

                build_order_allocations(order, currency="IRR")

            OrderStatusHistory.objects.create(
                order=order,
                old_status="",
                new_status=order.status,
                changed_by=user,
                note="Order created from cart.",
            )''',
)]

# Use processor-confirmed event timestamp, not the time of processing the callback.
p = "apps/orders/models.py"
REPLACEMENTS[p] = [(
    "def mark_paid(self):",
    "def mark_paid(self, paid_at=None):",
), (
    "self.paid_at = timezone.now()",
    "self.paid_at = paid_at or timezone.now()",
)]

# Successful capture -> ledger within the existing transactional payment flow.
p = "apps/payments/models.py"
REPLACEMENTS[p] = [(
    'def mark_success(self, gateway_reference="", gateway_response=None):',
    'def mark_success(self, gateway_reference="", gateway_response=None, confirmed_at=None):',
), (
    '''            now = timezone.now()

            payment.status = self.StatusChoices.SUCCESS''',
    '''            now = confirmed_at or timezone.now()
            if timezone.is_naive(now):
                raise ValidationError("Capture timestamp must be timezone-aware.")

            payment.status = self.StatusChoices.SUCCESS''',
), (
    '''            order.mark_paid()

            # Record independent fulfillment for each seller in this order.''',
    '''            order.mark_paid(paid_at=now)

            if getattr(settings, "SETTLEMENTS_LEDGER_ENABLED", False):
                from apps.settlements.services import post_captured_payment

                post_captured_payment(payment)

            # Record independent fulfillment for each seller in this order.''',
)]

# Prevent one processor capture reference being assigned to two paid orders.
p = "apps/payments/models.py"
REPLACEMENTS[p].append((
    '''                name="unique_successful_payment_per_order",
            ),
        ]''',
    '''                name="unique_successful_payment_per_order",
            ),
            models.UniqueConstraint(
                fields=["provider", "gateway_reference"],
                condition=Q(
                    status__in=("success", "refunded"),
                    gateway_reference__gt="",
                ),
                name="unique_provider_verified_capture_reference",
            ),
        ]''',
))

# Never allow user-supplied mock-success in production.
p = "apps/payments/views.py"
REPLACEMENTS[p] = [(
    '''from django.core.exceptions import ValidationError as DjangoValidationError''',
    '''from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError''',
), (
    '''        payment = self.get_object()
        old_status = payment.status

        serializer = PaymentSuccessSerializer(''',
    '''        if not getattr(settings, "SETTLEMENTS_ALLOW_MOCK_SUCCESS", False):
            return Response(
                {"detail": "Direct mock success is disabled. Use a verified payment integration."},
                status=status.HTTP_403_FORBIDDEN,
            )

        payment = self.get_object()
        old_status = payment.status

        serializer = PaymentSuccessSerializer(''',
)]

# Admin cannot turn an unverified refund into a finalized return state.
p = "apps/returns/services.py"
REPLACEMENTS[p] = [(
    '''    old_status = return_request.status

    return_request.status = ReturnRequest.Status.REFUNDED''',
    '''    from django.conf import settings
    if getattr(settings, "SETTLEMENTS_LEDGER_ENABLED", False):
        from django.db.models import Sum
        from apps.settlements.models import ConfirmedRefund
        verified = ConfirmedRefund.objects.filter(
            return_request_id=return_request.pk,
        ).aggregate(amount=Sum("amount"))["amount"] or Decimal("0")
        if verified < return_request.total_approved_amount:
            raise ValidationError(
                "The approved return amount has not been fully confirmed by the payment processor."
            )

    old_status = return_request.status

    return_request.status = ReturnRequest.Status.REFUNDED''',
)]

# Bank-confirmation proof cannot exceed funds eligible AFTER delivery/hold/refunds.
p = "apps/settlements/services.py"
REPLACEMENTS[p] = [(
    '''from django.core.exceptions import ValidationError''',
    '''from django.conf import settings
from django.core.exceptions import ValidationError''',
), (
    '''    if seller_balance(seller_id, currency) < amount:
        # A transfer might already have occurred externally.''',
    '''    if getattr(settings, "SETTLEMENTS_LEDGER_ENABLED", False):
        from apps.settlements.settlement_policy import payout_eligibility
        eligible = payout_eligibility(seller_id, currency)
        if Decimal(eligible["withdrawable_amount"]) < amount:
            raise ValidationError(
                "Payout exceeds eligible released balance. Reconcile with bank before posting."
            )
    if seller_balance(seller_id, currency) < amount:
        # A transfer might already have occurred externally.''',
)]

# Financial reports use verified refund events in ledger-enabled mode.
p = "apps/analytics/financial.py"
REPLACEMENTS[p] = [(
    'from dataclasses import dataclass',
    'from dataclasses import dataclass\nfrom django.conf import settings',
), (
    '''    refunded_payments = Payment.objects.filter(
        status=Payment.StatusChoices.REFUNDED,
    )
    refunded_payments = filter_event_window(
        refunded_payments,
        field_name="refunded_at",
        window=window,
    )''',
    '''    if getattr(settings, "SETTLEMENTS_LEDGER_ENABLED", False):
        from apps.settlements.models import ConfirmedRefund
        refunded_payments = filter_event_window(
            ConfirmedRefund.objects.all(),
            field_name="confirmed_at",
            window=window,
        )
    else:
        refunded_payments = Payment.objects.filter(
            status=Payment.StatusChoices.REFUNDED,
        )
        refunded_payments = filter_event_window(
            refunded_payments,
            field_name="refunded_at",
            window=window,
        )''',
)]

p = "apps/analytics/financial_reporting.py"
REPLACEMENTS[p] = [(
    'from datetime import datetime, timedelta',
    'from datetime import datetime, timedelta\nfrom django.conf import settings',
), (
    '''    queryset = filter_event_window(
        Payment.objects.filter(status__in=statuses),
        field_name=field_name,
        window=window,
    )

    group_expression = (
        TruncDate(
            field_name,
            tzinfo=timezone.get_current_timezone(),
        )
        if dimension == "date"
        else F("provider")
    )''',
    '''    if field_name == "refunded_at" and getattr(settings, "SETTLEMENTS_LEDGER_ENABLED", False):
        from apps.settlements.models import ConfirmedRefund
        queryset = filter_event_window(
            ConfirmedRefund.objects.all(),
            field_name="confirmed_at",
            window=window,
        )
        event_field = "confirmed_at"
        provider_field = "payment__provider"
    else:
        queryset = filter_event_window(
            Payment.objects.filter(status__in=statuses),
            field_name=field_name,
            window=window,
        )
        event_field = field_name
        provider_field = "provider"

    group_expression = (
        TruncDate(
            event_field,
            tzinfo=timezone.get_current_timezone(),
        )
        if dimension == "date"
        else F(provider_field)
    )''',
)]

p = "apps/settlements/urls.py"
REPLACEMENTS[p] = [(
    '''from django.urls import path''',
    '''from django.urls import include, path
from apps.settlements.payout_views import SellerPayoutEligibilityView, SettlementReadinessView''',
), (
    '''urlpatterns = [''',
    '''urlpatterns = [
    path("integrations/", include("apps.settlements.integration_urls")),
    path("seller/payout-eligibility/", SellerPayoutEligibilityView.as_view(), name="seller-payout-eligibility"),
    path("admin/readiness/", SettlementReadinessView.as_view(), name="settlement-readiness"),''',
)]

p = "config/settings/base.py"
REPLACEMENTS[p] = [(
    '''ROOT_URLCONF = "config.urls"''',
    '''# Financial feature rollout is OFF until historical records have been audited.
SETTLEMENTS_LEDGER_ENABLED = os.getenv("SETTLEMENTS_LEDGER_ENABLED", "False").lower() == "true"
# Direct user-triggered mock capture is dev-only; NEVER in production.
SETTLEMENTS_ALLOW_MOCK_SUCCESS = DEBUG and os.getenv("SETTLEMENTS_ALLOW_MOCK_SUCCESS", "True").lower() == "true"
SETTLEMENTS_ALLOW_SIGNED_MOCK_EVENTS = DEBUG and os.getenv("SETTLEMENTS_ALLOW_SIGNED_MOCK_EVENTS", "False").lower() == "true"
SETTLEMENTS_CAPTURE_BRIDGE_SECRET = os.getenv("SETTLEMENTS_CAPTURE_BRIDGE_SECRET", "")
SETTLEMENTS_REFUND_BRIDGE_SECRET = os.getenv("SETTLEMENTS_REFUND_BRIDGE_SECRET", "")
SETTLEMENTS_PAYOUT_BRIDGE_SECRET = os.getenv("SETTLEMENTS_PAYOUT_BRIDGE_SECRET", "")
SETTLEMENTS_PAYOUT_HOLD_DAYS = int(os.getenv("SETTLEMENTS_PAYOUT_HOLD_DAYS", "14"))

ROOT_URLCONF = "config.urls"''',
)]


def main():
    compiled = {}
    # Read and prepare ALL files before writing ANY of them.
    for filename, patches in REPLACEMENTS.items():
        path = Path(filename)
        if not path.is_file():
            raise SystemExit(f"Missing {filename}; no files modified")
        original = path.read_text(encoding="utf-8")
        new = original
        for old, replacement in patches:
            if replacement in new:
                continue
            elif old in new and new.count(old) == 1:
                new = new.replace(old, replacement, 1)
            else:
                raise SystemExit(
                    f"Unexpected source in {filename} (pattern not unique/missing); no files modified"
                )
        compile(new, filename, "exec")
        compiled[filename] = new
    for filename, content in compiled.items():
        Path(filename).write_text(content, encoding="utf-8")
    print("Stage 5 integration applied. Review git diff before testing/deploying.")


if __name__ == "__main__":
    main()
