from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings.cache import build_cache_settings


class CacheConfigurationTests(SimpleTestCase):
    def test_debug_defaults_to_local_cache_without_redis(self):
        config = build_cache_settings(debug=True)
        self.assertEqual(
            config["default"]["BACKEND"],
            "django.core.cache.backends.locmem.LocMemCache",
        )

    def test_configured_redis_uses_specified_host_and_database(self):
        url = "redis://redis:6379/1"
        config = build_cache_settings(debug=True, redis_url=url)
        self.assertEqual(config["default"]["LOCATION"], url)
        self.assertEqual(config["default"]["BACKEND"], "django_redis.cache.RedisCache")

    def test_explicit_local_cache_only_allowed_for_debug(self):
        config = build_cache_settings(debug=True, backend="locmem")
        self.assertIn("LocMemCache", config["default"]["BACKEND"])
        with self.assertRaises(ImproperlyConfigured):
            build_cache_settings(debug=False, backend="locmem", redis_url="redis://redis:6379/1")

    def test_production_requires_redis_url(self):
        with self.assertRaises(ImproperlyConfigured):
            build_cache_settings(debug=False)

    def test_invalid_backend_fails_early(self):
        with self.assertRaises(ImproperlyConfigured):
            build_cache_settings(debug=True, backend="unknown")
