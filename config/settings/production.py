import os

from .base import *

DEBUG = False

SECRET_KEY = os.environ["SECRET_KEY"]

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

CORS_ALLOW_ALL_ORIGINS = False

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True").lower() == "true"

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


## Throttling settings
REST_FRAMEWORK.setdefault("DEFAULT_THROTTLE_RATES", {})

REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update(
    {
        "auth_ip": os.getenv("AUTH_IP_THROTTLE_RATE", "20/hour"),
        "otp_ip": os.getenv("OTP_IP_THROTTLE_RATE", "10/hour"),
        "otp_email": os.getenv("OTP_EMAIL_THROTTLE_RATE", "5/hour"),
        "password_reset_ip": os.getenv(
            "PASSWORD_RESET_IP_THROTTLE_RATE",
            "10/hour",
        ),
        "password_reset_email": os.getenv(
            "PASSWORD_RESET_EMAIL_THROTTLE_RATE",
            "5/hour",
        ),
    }
)