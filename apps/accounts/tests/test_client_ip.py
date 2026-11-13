from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.accounts.client_ip import client_ip
from apps.accounts.throttles import AuthIPRateThrottle, OTPEmailRateThrottle


@override_settings(AUTH_TRUSTED_PROXY_NETWORKS=["10.23.0.0/24", "2001:db8:1::/64"])
class TrustedClientIPTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_untrusted_client_cannot_select_its_identity(self):
        request = self.factory.get("/", REMOTE_ADDR="192.0.2.10", HTTP_X_FORWARDED_FOR="198.51.100.2")
        self.assertEqual(client_ip(request), "192.0.2.10")

    def test_distinct_clients_behind_trusted_gateway_have_distinct_buckets(self):
        throttle = AuthIPRateThrottle()
        requests = [self.factory.get("/", REMOTE_ADDR="10.23.0.2", HTTP_X_FORWARDED_FOR=ip)
                    for ip in ["198.51.100.1", "198.51.100.2"]]
        self.assertNotEqual(*(throttle.get_cache_key(request, None) for request in requests))
        self.assertEqual(OTPEmailRateThrottle().get_ident(requests[0]), "198.51.100.1")

    def test_invalid_or_chained_forwarding_falls_back_to_peer(self):
        for forwarded in ["", "garbage", "198.51.100.1, 198.51.100.2"]:
            request = self.factory.get("/", REMOTE_ADDR="10.23.0.2", HTTP_X_FORWARDED_FOR=forwarded)
            self.assertEqual(client_ip(request), "10.23.0.2")

    def test_ipv6_is_canonicalized(self):
        request = self.factory.get("/", REMOTE_ADDR="2001:db8:1::1", HTTP_X_FORWARDED_FOR="2001:0db8:2::001")
        self.assertEqual(client_ip(request), "2001:db8:2::1")

    @override_settings(AUTH_TRUSTED_PROXY_NETWORKS=[])
    def test_no_proxy_is_trusted_by_default(self):
        request = self.factory.get("/", REMOTE_ADDR="10.23.0.2", HTTP_X_FORWARDED_FOR="198.51.100.1")
        self.assertEqual(client_ip(request), "10.23.0.2")
