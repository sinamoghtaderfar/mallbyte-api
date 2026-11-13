"""Move pre-hardening support files out of public MEDIA_ROOT.

Run after deploying the private storage change. Keep a backup until verified.
"""
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.support.management.commands.migrate_private_media import digest
from apps.support.models import TicketAttachment


class Command(BaseCommand):
    help = "Copy old public support attachments to the private root and verify integrity."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Copy the files (otherwise dry-run).")
        parser.add_argument("--purge-public", action="store_true", help="Remove old public files after verification.")

    def handle(self, *args, **options):
        source_root = Path(settings.MEDIA_ROOT).resolve()
        target_root = Path(settings.SUPPORT_PRIVATE_MEDIA_ROOT).resolve()
        if target_root.is_relative_to(source_root) or source_root.is_relative_to(target_root):
            raise CommandError("Public and private media roots must be separate.")
        if options["purge_public"] and not options["apply"]:
            raise CommandError("--purge-public requires --apply.")

        migrated = 0
        missing = 0
        for obj in TicketAttachment.objects.exclude(file="").iterator():
            name = obj.file.name
            source = (source_root / name).resolve()
            target = (target_root / name).resolve()
            if not source.is_relative_to(source_root) or not target.is_relative_to(target_root):
                raise CommandError("Unsafe attachment path detected.")
            if not source.exists():
                if not target.exists():
                    missing += 1
                    self.stderr.write(f"Missing attachment id={obj.pk}")
                continue
            if not options["apply"]:
                self.stdout.write(f"Would migrate attachment id={obj.pk}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
            if not target.is_file() or digest(source) != digest(target):
                raise CommandError(f"File verification failed for attachment id={obj.pk}")
            if options["purge_public"]:
                source.unlink()
            migrated += 1
        self.stdout.write(f"Processed: {migrated}; missing: {missing}.")
        if missing:
            raise CommandError("Some attachment files are missing; investigate before cleanup.")
