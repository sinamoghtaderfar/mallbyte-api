"""The legacy migration entry point must never purge a mismatching copy."""
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.support.models import SupportTicket, TicketAttachment


class LegacyMediaMigrationTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mallbyte-legacy-media-")
        self.addCleanup(temporary.cleanup)
        self.public = Path(temporary.name) / "public"
        self.private = Path(temporary.name) / "private"
        settings = override_settings(MEDIA_ROOT=self.public, SUPPORT_PRIVATE_MEDIA_ROOT=self.private)
        settings.enable()
        self.addCleanup(settings.disable)
        owner = User.objects.create_user(email="legacy-media@example.com")
        ticket = SupportTicket.objects.create(customer=owner, subject="Legacy")
        self.name = "support_attachments/legacy.txt"
        TicketAttachment.objects.create(ticket=ticket, uploaded_by=owner, file=self.name, size=4)
        self.source = self.public / self.name
        self.target = self.private / self.name
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"safe")

    def migrate(self, **options):
        call_command("migrate_support_attachments", stdout=StringIO(), **options)

    def test_equal_size_different_content_cannot_be_purged(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"evil")
        with self.assertRaises(CommandError):
            self.migrate(apply=True, purge_public=True)
        self.assertEqual(self.source.read_bytes(), b"safe")
        self.assertEqual(self.target.read_bytes(), b"evil")

    def test_copy_verify_and_purge_is_resumable(self):
        self.migrate()
        self.assertFalse(self.target.exists())
        self.migrate(apply=True)
        self.assertEqual(self.target.read_bytes(), b"safe")
        self.assertTrue(self.source.exists())
        self.migrate(apply=True, purge_public=True)
        self.assertFalse(self.source.exists())
        self.migrate(apply=True, purge_public=True)
        self.assertEqual(self.target.read_bytes(), b"safe")

    def test_nested_public_root_is_rejected(self):
        with override_settings(MEDIA_ROOT=self.private / "public"):
            with self.assertRaises(CommandError):
                self.migrate(apply=True)
