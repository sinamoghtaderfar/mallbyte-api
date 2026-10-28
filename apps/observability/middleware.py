"""Fail-open request instrumentation: monitoring must not break the service."""
import logging
import time
import uuid

from apps.observability.sanitization import scrub_request_id
from apps.observability.services import create_error_log_from_exception, create_request_log

logger = logging.getLogger(__name__)


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = scrub_request_id(request.headers.get("X-Request-ID")) or str(uuid.uuid4())
        request.observability_request_id = request_id
        started_at = time.monotonic()
        response = self.get_response(request)
        duration_ms = int((time.monotonic() - started_at) * 1000)
        try:
            request.observability_request_log = create_request_log(
                request=request, response=response, duration_ms=duration_ms,
                request_id=request_id,
            )
        except Exception:
            # Use Python logging, not database observability, to avoid recursion.
            logger.exception("Could not persist request instrumentation")
            request.observability_request_log = None
        response["X-Request-ID"] = request_id
        return response

    def process_exception(self, request, exception):
        try:
            create_error_log_from_exception(
                request=request, exception=exception,
                request_log=getattr(request, "observability_request_log", None),
            )
        except Exception:
            logger.exception("Could not persist exception instrumentation")
        return None
