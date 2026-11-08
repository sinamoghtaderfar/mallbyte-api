"""Explicit, resumable migration of legacy public evidence and reports.

Schema migrations change storage metadata only. This command never changes
database file names, verifies bytes, and defaults to a read-only dry run.
"""
import hashlib
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.analytics.models import AnalyticsGeneratedReport
from apps.returns.models import ReturnAttachment, ReturnShipment
from apps.support.models import TicketAttachment


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.digest()


class Command(BaseCommand):
    help = "Migrate public return/support evidence and financial reports to private storage (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Copy files and verify SHA-256 integrity.")
        parser.add_argument("--purge-public", action="store_true", help="Delete verified public copies; requires --apply.")

    def handle(self, *args, **options):
        if options["purge_public"] and not options["apply"]:
            raise CommandError("--purge-public requires --apply.")
        public_root = Path(settings.MEDIA_ROOT).resolve()
        sources = (
            (AnalyticsGeneratedReport, "file"), (ReturnAttachment, "file"),
            (ReturnShipment, "shipping_label"), (TicketAttachment, "file"),
        )
        missing = 0
        processed = 0
        for model, field_name in sources:
            storage = model._meta.get_field(field_name).storage
            private_root = Path(storage.location).resolve()
            if private_root.is_relative_to(public_root) or public_root.is_relative_to(private_root):
                raise CommandError("Public and private media roots must be separate.")
            rows = model.objects.exclude(**{field_name: ""}).exclude(**{f"{field_name}__isnull": True})
            for obj in rows.iterator():
                name = getattr(obj, field_name).name
                source = (public_root / name).resolve()
                target = (private_root / name).resolve()
                if not source.is_relative_to(public_root) or not target.is_relative_to(private_root):
                    raise CommandError("Unsafe stored file path detected.")
                if not source.is_file():
                    if not target.is_file():
                        missing += 1
                        self.stderr.write(f"Missing {model._meta.label} id={obj.pk}")
                    continue
                if not options["apply"]:
                    self.stdout.write(f"Would copy {model._meta.label} id={obj.pk}")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
                        temporary_path = Path(temporary.name)
                        try:
                            with source.open("rb") as original:
                                shutil.copyfileobj(original, temporary)
                        except BaseException:
                            temporary_path.unlink(missing_ok=True)
                            raise
                    if digest(source) != digest(temporary_path):
                        temporary_path.unlink()
                        raise CommandError("Copied file failed SHA-256 verification.")
                    temporary_path.replace(target)
                if not target.is_file() or digest(source) != digest(target):
                    raise CommandError(f"Private copy differs for {model._meta.label} id={obj.pk}; public copy preserved.")
                if options["purge_public"]:
                    source.unlink()
                processed += 1
        self.stdout.write(f"Verified copies: {processed}; missing files: {missing}.")
        if missing:
            raise CommandError("Missing files require investigation; do not retire backups.")
