from django.test import RequestFactory, TestCase, override_settings

from apps.accounts.models import User
from apps.rbac.utils import get_client_ip, log_admin_action


@override_settings(AUTH_TRUSTED_PROXY_NETWORKS=["10.23.0.0/24", "2001:db8:1::/64"])
class AuditClientIPTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_superuser(email="admin@example.com", password="admin-password")

    def test_spoofed_forwarded_ip_cannot_be_written_to_admin_audit(self):
        request = self.factory.post("/", REMOTE_ADDR="192.0.2.10", HTTP_X_FORWARDED_FOR="198.51.100.100")
        log = log_admin_action(self.admin, "change_permission", request=request)
        log.refresh_from_db()
        self.assertEqual(log.ip_address, "192.0.2.10")

    def test_audit_uses_the_canonical_single_address_from_a_trusted_peer(self):
        request = self.factory.post("/", REMOTE_ADDR="2001:db8:1::1", HTTP_X_FORWARDED_FOR="2001:0db8:2::001")
        log = log_admin_action(self.admin, "change_permission", request=request)
        log.refresh_from_db()
        self.assertEqual(log.ip_address, "2001:db8:2::1")

    def test_chained_header_falls_back_to_trusted_peer_address(self):
        request = self.factory.post("/", REMOTE_ADDR="10.23.0.2", HTTP_X_FORWARDED_FOR="198.51.100.1, 198.51.100.2")
        self.assertEqual(get_client_ip(request), "10.23.0.2")

    def test_missing_peer_produces_null_audit_ip_instead_of_invalid_ip(self):
        request = self.factory.post("/", REMOTE_ADDR="", HTTP_X_FORWARDED_FOR="198.51.100.100")
        log = log_admin_action(self.admin, "change_permission", request=request)
        log.refresh_from_db()
        self.assertIsNone(log.ip_address)
