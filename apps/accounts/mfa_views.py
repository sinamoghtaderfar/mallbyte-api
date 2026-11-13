"""Second-factor endpoints: email OTP -> short-lived challenge -> TOTP/recovery."""

import hashlib

from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .cookies import set_refresh_cookie
from .mfa import (
    consume_recovery_code,
    decrypt_secret,
    encrypt_secret,
    is_privileged,
    issue_privileged_tokens,
    match_totp,
    new_recovery_codes,
    new_secret,
    provisioning_uri,
)
from .mfa_models import AdminMFAChallenge, AdminMFADevice
from .serializers import UserSerializer
from .throttles import MFAIPRateThrottle


class ChallengeInput(serializers.Serializer):
    challenge = serializers.CharField(max_length=128)


class SetupInput(ChallengeInput):
    password = serializers.CharField(write_only=True)


class VerifyInput(ChallengeInput):
    code = serializers.CharField(max_length=64, write_only=True)


def _get_challenge(raw):
    version, separator, _nonce = raw.partition(".")
    if not separator or not version.isascii() or not version.isdigit():
        return None
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    challenge = (
        # Lock the related user too: a concurrent security change either wins
        # before this epoch check or revokes the session issued by this request.
        AdminMFAChallenge.objects.select_for_update()
        .select_related("user")
        .filter(token_hash=token_hash)
        .first()
    )
    if (
        challenge is None
        or int(version) != challenge.user.auth_version
        or challenge.used_at is not None
        or challenge.expires_at <= timezone.now()
        or challenge.attempts >= 5
        or not challenge.user.is_active
        or challenge.user.is_deleted
        or not is_privileged(challenge.user)
    ):
        return None
    return challenge


def _invalid():
    return Response({"detail": "Invalid or expired MFA challenge."}, status=status.HTTP_400_BAD_REQUEST)


def _authenticated_response(user, device, recovery_codes=None):
    refresh = issue_privileged_tokens(user, device)
    result = {
        "user": UserSerializer(user).data,
        "access": str(refresh.access_token),
        "is_new": False,
    }
    if recovery_codes is not None:
        result["recovery_codes"] = recovery_codes
    response = Response(result)
    set_refresh_cookie(response, str(refresh))
    return response


class AdminMFASetupView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [MFAIPRateThrottle]

    def post(self, request):
        serializer = SetupInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            challenge = _get_challenge(serializer.validated_data["challenge"])
            if not challenge:
                return _invalid()
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            user = challenge.user
            if not user.has_usable_password() or not user.check_password(serializer.validated_data["password"]):
                return Response({"detail": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)

            device, _created = AdminMFADevice.objects.select_for_update().get_or_create(
                user=user, defaults={"encrypted_secret": encrypt_secret(new_secret())}
            )
            if device.enabled:
                return Response({"detail": "MFA already enrolled."}, status=status.HTTP_409_CONFLICT)
            secret = new_secret()
            device.encrypted_secret = encrypt_secret(secret)
            device.save(update_fields=["encrypted_secret", "updated_at"])
            challenge.password_confirmed = True
            challenge.attempts = 0
            challenge.save(update_fields=["password_confirmed", "attempts"])
        return Response({
            "secret": secret,
            "otpauth_uri": provisioning_uri(user, secret),
            "message": "Add this secret to your authenticator, then confirm its six-digit code.",
        })


class AdminMFACompleteView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [MFAIPRateThrottle]

    def post(self, request):
        serializer = VerifyInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            challenge = _get_challenge(serializer.validated_data["challenge"])
            if not challenge or not challenge.password_confirmed:
                return _invalid()
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            device = AdminMFADevice.objects.select_for_update().filter(user=challenge.user).first()
            if not device or device.enabled:
                return _invalid()
            counter = match_totp(decrypt_secret(device.encrypted_secret), serializer.validated_data["code"], device.last_counter)
            if counter is None:
                return Response({"detail": "Invalid authenticator code."}, status=status.HTTP_400_BAD_REQUEST)
            recovery, hashes = new_recovery_codes()
            device.last_counter = counter
            device.recovery_codes = hashes
            device.enabled = True
            device.save(update_fields=["last_counter", "recovery_codes", "enabled", "updated_at"])
            challenge.used_at = timezone.now()
            challenge.save(update_fields=["used_at"])
            return _authenticated_response(challenge.user, device, recovery_codes=recovery)


class AdminMFAVerifyView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [MFAIPRateThrottle]

    def post(self, request):
        serializer = VerifyInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            challenge = _get_challenge(serializer.validated_data["challenge"])
            if not challenge:
                return _invalid()
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            device = AdminMFADevice.objects.select_for_update().filter(user=challenge.user, enabled=True).first()
            if not device:
                return _invalid()

            code = serializer.validated_data["code"].strip()
            counter = match_totp(decrypt_secret(device.encrypted_secret), code, device.last_counter)
            if counter is not None:
                device.last_counter = counter
                device.save(update_fields=["last_counter", "updated_at"])
            elif consume_recovery_code(device, code):
                device.save(update_fields=["recovery_codes", "updated_at"])
            else:
                return Response({"detail": "Invalid authenticator or recovery code."}, status=status.HTTP_400_BAD_REQUEST)

            challenge.used_at = timezone.now()
            challenge.save(update_fields=["used_at"])
            return _authenticated_response(challenge.user, device)
