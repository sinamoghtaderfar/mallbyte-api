import os

from .base import *

DEBUG = False

# Separate, stable Fernet key for encrypted privileged authenticator seeds.
MFA_FERNET_KEY = os.environ["MFA_FERNET_KEY"]
# Django admin uses session passwords, not the MFA-protected JWT flow.
# Keep it unavailable in production until Django admin-specific MFA is integrated.
DJANGO_ADMIN_ENABLED = False

SECRET_KEY = os.environ["SECRET_KEY"]

# Require TLS for external PostgreSQL connections. verify-full is recommended
# when a database provider supplies a CA certificate and hostname.
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")
if DB_SSLMODE not in {"require", "verify-ca", "verify-full"}:
    raise RuntimeError("Production PostgreSQL requires SSL: DB_SSLMODE must be require, verify-ca or verify-full")
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = DB_SSLMODE
    if os.getenv("DB_SSLROOTCERT"):
        DATABASES["default"]["OPTIONS"]["sslrootcert"] = os.environ["DB_SSLROOTCERT"]
    DATABASES["default"]["CONN_MAX_AGE"] = int(os.getenv("DB_CONN_MAX_AGE", "60"))
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True


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

# Docker probes use internal HTTP; exempt ONLY the non-sensitive liveness route.
# All application/API endpoints continue to redirect to HTTPS.
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True").lower() == "true"

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Base settings may have been imported with DEBUG=True; never let that
# weaken authentication cookies in this explicitly production-only module.
AUTH_COOKIE_SECURE = True

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
        "mfa_ip": os.getenv("MFA_IP_THROTTLE_RATE", "10/hour"),
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

# Minimize disclosure from exception and worker result representations.
OBSERVABILITY_STORE_TRACEBACK = False
OBSERVABILITY_STORE_EXCEPTION_MESSAGES = False
OBSERVABILITY_STORE_TASK_RESULTS = False
