"""Trusted checkout settings; clients cannot set the delivery charge or hold TTL."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone


def shipping_charge():
    # Preserve the existing zero-charge default until operators configure a
    # tariff. A future delivery quote service can replace this single boundary.
    try:
        value = Decimal(str(getattr(settings, "CHECKOUT_SHIPPING_COST", "0")))
    except InvalidOperation as exc:
        raise ImproperlyConfigured("CHECKOUT_SHIPPING_COST must be a valid integer amount.") from exc
    if not value.is_finite() or value < 0 or value != value.to_integral_value():
        raise ImproperlyConfigured("CHECKOUT_SHIPPING_COST must be a nonnegative integer amount.")
    return value


def reservation_deadline():
    seconds = int(getattr(settings, "ORDER_RESERVATION_TTL_SECONDS", 1800))
    if seconds < 60:
        raise ImproperlyConfigured("ORDER_RESERVATION_TTL_SECONDS must be at least 60.")
    return timezone.now() + timedelta(seconds=seconds)
