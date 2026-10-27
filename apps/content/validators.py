"""Input policy for CMS content consumed by browser storefronts.

Text fields are plain text/Markdown sources, NOT trusted raw HTML.
The frontend must render them as escaped text or sanitized Markdown.
"""
import re
from urllib.parse import urlsplit
from rest_framework import serializers

_HTML_TAG = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
_BAD_URL_CHARS = re.compile(r"[\x00-\x20\x7f\\]")
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def validate_plain_text(value):
    if _HTML_TAG.search(value or ""):
        raise serializers.ValidationError(
            "Raw HTML tags are not accepted. Use plain text or Markdown."
        )
    return value


def validate_link(value):
    """Allow root-relative internal links or HTTPS links without credentials."""
    if not value:
        return value
    if _BAD_URL_CHARS.search(value) or value.startswith("//"):
        raise serializers.ValidationError("Invalid or unsafe URL.")
    if value.startswith("/"):
        return value
    parts = urlsplit(value)
    try:
        valid_port = parts.port is None or 1 <= parts.port <= 65535
    except ValueError:
        valid_port = False
    if (parts.scheme.lower() != "https" or not parts.hostname
            or parts.username is not None or parts.password is not None
            or not valid_port or parts.fragment):
        raise serializers.ValidationError(
            "Use an internal /path or a safe HTTPS URL without credentials."
        )
    return value


def validate_image_upload(value):
    if value is None:
        return value
    if value.size > MAX_IMAGE_BYTES:
        raise serializers.ValidationError("Maximum image upload size is 8 MB.")
    # DRF's ImageField validates image encoding with Pillow.
    return value


def validate_publication_window(attrs, instance=None):
    start = attrs.get("starts_at", getattr(instance, "starts_at", None))
    end = attrs.get("ends_at", getattr(instance, "ends_at", None))
    if start and end and start >= end:
        raise serializers.ValidationError(
            {"ends_at": "End time must be later than start time."}
        )
    return attrs


def reject_direct_publication(initial_data):
    if "status" in initial_data and initial_data["status"] != "draft":
        raise serializers.ValidationError({
            "status": "Use the dedicated publish/archive action to change status."
        })
    if "published_at" in initial_data:
        raise serializers.ValidationError({
            "published_at": "Publication timestamps are managed by the server."
        })
