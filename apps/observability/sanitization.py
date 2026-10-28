"""Defense-in-depth masking of monitoring data; never log bodies or headers."""
import re
from urllib.parse import parse_qsl, urlencode

# Allowlisted parameters are intentionally small and must not contain secrets.
SAFE_QUERY_PARAMETERS = frozenset({
    "page", "page_size", "ordering", "sort", "method", "status_code",
    "slow", "error", "severity", "status", "source", "window",
})
SENSITIVE = re.compile(
    r"(?i)(\b(?:access_token|refresh_token|token|api[_-]?key|"
    r"password|secret|authorization|sessionid|otp|code)\b[\"\']?\s*[:=]\s*)"
    r"(?:[\"']?)[^\s,;\"']+"
)
BEARER = re.compile(r"(?i)\bBearer\s+[a-z0-9._~+/-]+")


def scrub_text(value, *, limit=1000):
    value = str(value or "")[:limit]
    value = BEARER.sub("Bearer [REDACTED]", value)
    return SENSITIVE.sub(r"\1[REDACTED]", value)


def scrub_query(raw_query):
    """Preserve benign filters, but never retain unknown parameter values."""
    pairs = []
    for key, value in parse_qsl((raw_query or "")[:4096], keep_blank_values=True)[:24]:
        clean_key = re.sub(r"[^a-zA-Z0-9_\-]", "", key)[:40]
        if not clean_key:
            continue
        if clean_key.lower() in SAFE_QUERY_PARAMETERS:
            clean_value = scrub_text(value, limit=80)
        else:
            clean_value = "[REDACTED]"
        pairs.append((clean_key, clean_value))
    return urlencode(pairs)


def scrub_request_id(value):
    return re.sub(r"[^A-Za-z0-9_.:-]", "", str(value or ""))[:100]
