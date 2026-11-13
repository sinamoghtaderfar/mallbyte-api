"""Verified financial evidence fixtures; these helpers never execute a transfer."""
from django.utils import timezone

from apps.payments.models import Payment
from apps.settlements.models import ConfirmedRefund


def record_verified_return_evidence(claim):
    claim.refresh_from_db()
    payment = Payment.objects.create(
        order=claim.order, user=claim.customer,
        amount=claim.order.total_amount, status=Payment.StatusChoices.SUCCESS,
        paid_at=timezone.now(),
    )
    return ConfirmedRefund.objects.create(
        payment=payment, return_request=claim,
        gateway_reference=f"verified-test-refund-{claim.pk}",
        idempotency_key=f"verified-test-refund-{claim.pk}", currency="IRR",
        amount=claim.total_approved_amount, confirmed_at=timezone.now(),
    )
