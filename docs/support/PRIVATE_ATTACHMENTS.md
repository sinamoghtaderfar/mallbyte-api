# Private support attachments

Support evidence is stored outside the public media directory (`SUPPORT_PRIVATE_MEDIA_ROOT`, default `private_media`). Never serve that directory from a web server or public CDN. The API never serializes the underlying storage URL; clients download from `GET /api/support/tickets/<ticket_id>/attachments/<attachment_id>/download/` with their existing Bearer token.

## Accepted uploads

PDF, PNG, JPG/JPEG and UTF-8 TXT, up to 8 MiB. Extensions, file signatures and image decoder checks are enforced. Files are delivered as attachments with `nosniff` and `Cache-Control: private, no-store`. These checks are not a substitute for malware scanning: consider antivirus/sandboxing and rate limits for a public deployment.

## Existing file migration

**Important:** A Django schema migration changes only the FileField storage configuration; it does *not* move existing files.

1. Back up your database and `MEDIA_ROOT`. Confirm `SUPPORT_PRIVATE_MEDIA_ROOT` is outside `MEDIA_ROOT` and persisted across deployments.
2. Deploy backend with private downloads enabled and keep old public media isolated from unauthenticated access at the reverse proxy.
3. Run `python manage.py migrate_support_attachments` (dry run), then `python manage.py migrate_support_attachments --apply`.
4. Verify downloads work for authorized users and fail for unauthorized users.
5. Only after verification and backups, run `python manage.py migrate_support_attachments --apply --purge-public`. Files already moved to private storage are skipped. Confirm the old `media/support/attachments` area is empty.
6. Never point `/media/` or Django's debug `static(..., document_root=MEDIA_ROOT)` at the private storage directory.

The provided local filesystem storage is intended for a single persistent filesystem. Multi-node deployments need a private object-storage backend with equivalent access controls.
