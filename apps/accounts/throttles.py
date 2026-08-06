import hashlib

from rest_framework.throttling import SimpleRateThrottle


class ScopedIPRateThrottle(SimpleRateThrottle):
    scope = None

    def get_cache_key(self, request, view):
        if not self.scope:
            return None

        ident = self.get_ident(request)

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class EmailFieldRateThrottle(SimpleRateThrottle):
    scope = None
    email_field = "email"

    def get_cache_key(self, request, view):
        if not self.scope:
            return None

        email = None

        if hasattr(request, "data") and hasattr(request.data, "get"):
            email = request.data.get(self.email_field)

        if not email and hasattr(request, "query_params"):
            email = request.query_params.get(self.email_field)

        if email:
            normalized_email = str(email).strip().lower()
            ident = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class AuthIPRateThrottle(ScopedIPRateThrottle):
    scope = "auth_ip"


class OTPIPRateThrottle(ScopedIPRateThrottle):
    scope = "otp_ip"


class OTPEmailRateThrottle(EmailFieldRateThrottle):
    scope = "otp_email"


class PasswordResetIPRateThrottle(ScopedIPRateThrottle):
    scope = "password_reset_ip"


class PasswordResetEmailRateThrottle(EmailFieldRateThrottle):
    scope = "password_reset_email"