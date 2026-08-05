import time
import uuid

from apps.observability.services import (
    create_error_log_from_exception,
    create_request_log,
)


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.observability_request_id = request_id

        started_at = time.monotonic()

        response = self.get_response(request)

        duration_ms = int((time.monotonic() - started_at) * 1000)

        request_log = create_request_log(
            request=request,
            response=response,
            duration_ms=duration_ms,
            request_id=request_id,
        )

        request.observability_request_log = request_log

        response["X-Request-ID"] = request_id

        return response

    def process_exception(self, request, exception):
        request_log = getattr(request, "observability_request_log", None)

        create_error_log_from_exception(
            request=request,
            exception=exception,
            request_log=request_log,
        )

        return None