"""Build Django's cache configuration without network calls at import time."""

from django.core.exceptions import ImproperlyConfigured


def build_cache_settings(*, debug, backend=None, redis_url=None):
    """Use Redis when configured; allow explicit/local fallback only in DEBUG.

    Never silently switch a configured Redis cache to process-local memory.
    """
    redis_url = (redis_url or "").strip()
    selected = (backend or ("redis" if redis_url or not debug else "locmem")).strip().lower()

    if selected == "locmem":
        if not debug:
            raise ImproperlyConfigured("LocMemCache is not permitted when DEBUG is False.")
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }

    if selected != "redis":
        raise ImproperlyConfigured("CACHE_BACKEND must be 'redis' or 'locmem'.")

    if not redis_url:
        raise ImproperlyConfigured(
            "CACHE_REDIS_URL (or REDIS_URL) is required for Redis caching."
        )

    return {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": redis_url,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "SOCKET_CONNECT_TIMEOUT": 5,
                "SOCKET_TIMEOUT": 5,
                "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor",
            },
        }
    }
