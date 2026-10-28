"""Bounded database-side aggregation for the admin observability dashboard."""
import math
from datetime import timedelta

from django.db.models import Avg, Count
from django.db.models.functions import TruncHour, TruncMinute
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.observability.models import ErrorLog, ObservabilityAlert, RequestLog

WINDOWS = {"1h": timedelta(hours=1), "6h": timedelta(hours=6),
           "24h": timedelta(hours=24), "7d": timedelta(days=7)}


def build_metrics(window="24h"):
    if window not in WINDOWS:
        raise ValidationError({"window": "Choose one of: 1h, 6h, 24h, 7d."})

    now = timezone.now()
    qs = RequestLog.objects.filter(created_at__gte=now - WINDOWS[window])
    errors = ErrorLog.objects.filter(created_at__gte=now - WINDOWS[window])
    total = qs.count()
    error_requests = qs.filter(status_code__gte=500).count()
    # An indexed ORDER BY + OFFSET avoids materializing all latency values in Python.
    p95 = qs.order_by("duration_ms").values_list("duration_ms", flat=True)[
        max(0, math.ceil(total * .95) - 1)
    ] if total else 0
    bucket = TruncMinute("created_at") if window == "1h" else TruncHour("created_at")
    trend = list(
        qs.annotate(bucket=bucket).values("bucket")
        .annotate(requests=Count("pk"), average_ms=Avg("duration_ms"))
        .order_by("bucket")
    )
    return {
        "window": "last_24_hours" if window == "24h" else window,  # legacy response
        "window_key": window,
        "requests_count": total,
        "error_logs_count": errors.count(),
        "open_alerts_count": ObservabilityAlert.objects.filter(
            status=ObservabilityAlert.StatusChoices.OPEN,
        ).count(),
        "slow_requests_count": qs.filter(duration_ms__gte=1000).count(),
        "average_duration_ms": qs.aggregate(avg=Avg("duration_ms"))["avg"] or 0,
        "p95_duration_ms": p95,
        "error_rate_percent": round(error_requests * 100 / total, 2) if total else 0,
        "status_codes": list(qs.values("status_code").annotate(count=Count("pk")).order_by("status_code")),
        "top_paths": list(qs.values("path").annotate(count=Count("pk")).order_by("-count")[:10]),
        "open_alerts_by_severity": list(
            ObservabilityAlert.objects.filter(status=ObservabilityAlert.StatusChoices.OPEN)
            .values("severity").annotate(count=Count("pk")).order_by("severity")
        ),
        "request_trend": trend,
    }
