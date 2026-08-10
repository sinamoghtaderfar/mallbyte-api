from django.conf import settings
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken


def get_refresh_cookie_name() -> str:
    return getattr(settings, "AUTH_REFRESH_COOKIE_NAME", "mallbyte_refresh")


def get_refresh_cookie_path() -> str:
    return getattr(settings, "AUTH_REFRESH_COOKIE_PATH", "/api/auth/")


def set_refresh_cookie(response: Response, refresh_token: str) -> Response:
    response.set_cookie(
        key=get_refresh_cookie_name(),
        value=refresh_token,
        max_age=int(RefreshToken.lifetime.total_seconds()),
        httponly=True,
        secure=getattr(settings, "AUTH_COOKIE_SECURE", not settings.DEBUG),
        samesite=getattr(settings, "AUTH_COOKIE_SAMESITE", "Lax"),
        path=get_refresh_cookie_path(),
    )
    return response


def clear_refresh_cookie(response: Response) -> Response:
    response.delete_cookie(
        key=get_refresh_cookie_name(),
        path=get_refresh_cookie_path(),
        samesite=getattr(settings, "AUTH_COOKIE_SAMESITE", "Lax"),
    )
    return response
