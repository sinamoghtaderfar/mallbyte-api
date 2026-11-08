from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .auth_tokens import identity_token_valid
from .mfa import privileged_token_valid


class MFAGuardedJWTAuthentication(JWTAuthentication):
    """Reject legacy/non-MFA JWTs for staff and superusers at every API endpoint."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not identity_token_valid(user, validated_token):
            raise AuthenticationFailed("Please verify your email and sign in again.", code="session_expired")
        if not privileged_token_valid(user, validated_token):
            raise AuthenticationFailed(
                "A verified MFA session is required for privileged accounts.",
                code="mfa_required",
            )
        return user
