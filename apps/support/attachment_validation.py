"""Conservative upload policy: safe download-only formats, size and content checks."""

from pathlib import Path

from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

MAX_SUPPORT_ATTACHMENT_BYTES = 8 * 1024 * 1024
SUPPORT_ATTACHMENT_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".txt"})
SUPPORT_ATTACHMENT_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
}


def validate_support_attachment(upload):
    """Never trust the filename's MIME type or the browser-provided Content-Type."""
    extension = Path(upload.name).suffix.lower()
    if extension not in SUPPORT_ATTACHMENT_EXTENSIONS:
        raise serializers.ValidationError("Allowed attachments: PDF, PNG, JPG, JPEG, or TXT.")

    if not upload.size or upload.size > MAX_SUPPORT_ATTACHMENT_BYTES:
        raise serializers.ValidationError("Attachment must be between 1 byte and 8 MB.")

    try:
        upload.seek(0)
        header = upload.read(16)
        upload.seek(0)

        if extension == ".pdf" and not header.startswith(b"%PDF-"):
            raise serializers.ValidationError("Invalid PDF file.")
        if extension == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise serializers.ValidationError("Invalid PNG file.")
        if extension in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
            raise serializers.ValidationError("Invalid JPEG file.")

        if extension in {".png", ".jpg", ".jpeg"}:
            try:
                with Image.open(upload) as img:
                    expected = "PNG" if extension == ".png" else "JPEG"
                    if img.format != expected:
                        raise serializers.ValidationError("Image type does not match its extension.")
                    img.verify()
            except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
                raise serializers.ValidationError("Invalid or corrupted image file.") from exc

        if extension == ".txt":
            body = upload.read()
            if b"\x00" in body:
                raise serializers.ValidationError("TXT attachment must contain plain UTF-8 text.")
            try:
                body.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise serializers.ValidationError("TXT attachment must be UTF-8 encoded.") from exc
    finally:
        upload.seek(0)

    return upload
