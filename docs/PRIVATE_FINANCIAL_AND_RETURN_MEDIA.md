# Private reports and return evidence

Financial reports, return evidence and return shipping labels are private. They
use the existing persisted private support-media volume by default. An optional
`PRIVATE_MEDIA_ROOT` Django setting can select another private filesystem root;
it must be persisted and shared by web and workers, outside `MEDIA_ROOT`.

API fields `file`, `file_url` and `shipping_label` now contain protected API
download URLs. Clients must send their Bearer token to these URLs. Reports require
the existing report-management permission. Customers see their own uploaded
evidence; sellers see only buyer-uploaded evidence linked to their own items.
Request-wide or internal uploads are unavailable to sellers. Return shipping
labels are available to the customer and return administrators. All downloads
use attachment disposition, `nosniff` and `private, no-store`.

## Deployment and existing files

1. Back up the DB and both media volumes. Deploy the Nginx rules denying legacy
   `/media/analytics/`, `/media/returns/` and `/media/support/attachments/` first.
   Block the same paths at any external CDN or alternate public media origin.
2. Deploy code and run schema migrations. They do not copy existing files.
3. Run `python manage.py migrate_private_media` for a dry run. Investigate missing
   records/files. Run `python manage.py migrate_private_media --apply` to copy and
   verify SHA-256 integrity. The command preserves DB file names and can resume.
4. Test authorized/unauthorized downloads and confirm web and worker processes
   share the private volume. Only then run the explicit
   `migrate_private_media --apply --purge-public` command to remove verified old
   public copies. Keep backups according to retention policy.
5. Keep the deny rules permanently; purge any previously cached sensitive files
   from public CDNs. Never expose the private volume through a web-server alias.

This filesystem backend requires shared persistent storage for multiple nodes.
For object storage, implement an equivalent private backend and migration plan;
public object URLs are not supported.
