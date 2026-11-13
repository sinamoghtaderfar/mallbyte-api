# Catalog integrity, query behavior and upgrade requirements

This change depends on the catalog moderation/security PR. It introduces product/variant nonnegative selling-price and dimension constraints, compare prices at least equal to selling prices, one main image and one default variant per product. Product and variant `final_price` both return the selling price; compare price is a display reference, never the chargeable price.

Nested writes validate duplicate/existing variant SKUs before mutation and execute atomically. Constraint races return a DRF validation error after rollback. Explicit empty images/variants/tags lists clear those collections; omitted collections remain intact. Component parent IDs, category cycles, supported labels, image size and bounded CSV/XLSX imports now validate at the API boundary. XLSX compressed uploads are limited to 8 MB and expanded archive entries to 64 MB, and imports read at most 1001 rows to enforce the 1000-row limit. Imports share the normal product serializer: required catalog fields must be present and invalid rows return sanitized row errors.

Catalog list/featured/seller/related/export and comparison paths share stock aggregates and main-image prefetches. The in-stock filter uses an EXISTS subquery so a second warehouse join cannot multiply stock totals. Featured and seller listings now return the standard paginated response (`count`, `next`, `previous`, `results`); frontend callers must read `results`. Comparison accepts at most 20 distinct positive product IDs and returns validation errors for malformed IDs. Wishlist/recent activity and category trees avoid per-row/per-descendant lookups. View counts use atomic database increments.

ProductsConfig registers QR generation at startup. A product QR PNG is created after commit; failures are logged without leaking exception details or failing the saved product. `backfill_product_qr_codes` lists missing assets by default; `--apply --limit 1000` performs a bounded, repeatable backfill after storage is available. Product saves no longer run the obsolete email-only low-stock receiver: inventory movement services already create authoritative threshold-crossing notifications (`apps/inventory/services.py`). This does not add SMS/email/push delivery guarantees.

## Migration 0011

The migration runs a preflight before changing schema or data. It refuses invalid existing prices/dimensions, multiple main images and multiple default variants, returning counts only. Operators must review and reconcile those records explicitly; the migration never silently changes prices, chooses defaults or discards images. Test the migration against a restored staging copy before deployment and schedule an appropriate table-lock window for constraints.

The unused legacy `ProductTag` mapping is consolidated into the existing `Product.tags` M2M in batches, retaining the union of associations, before the redundant table is removed. Reverse migration recreates legacy associations. As with any removed redundant table, retain a database backup if legacy mapping row IDs/creation timestamps are required for historical inspection; those metadata fields are not represented by the M2M.

## Existing historical migrations needing environment verification

`apps/products/migrations/0009_remove_product_stock.py` removes the old scalar product stock without transferring it to warehouse Stock rows. `0010_delete_review.py` deletes the old product Review table without transferring its rows to the reviews app. These migrations predate this remediation and may already have run. Rewriting applied migration history would create inconsistent deployments and cannot recover deleted data.

For an environment still before these migrations, export/archive the old stock and Review data and reconcile it on a restored staging copy before proceeding. Warehouse stock requires an explicit warehouse allocation decision; review migration requires customer identity, moderation-state and duplicate mapping decisions. For an environment already past them, compare current inventory/reviews to retained backups and restore missing logical records only through a reviewed reconciliation plan. Do not fabricate stock allocation or approved-review status. Production history and backups were not accessed, so the presence or extent of historical data loss remains unverified.

Variant selection in cart/order/warehouse stock is a separate product-scope decision: this patch corrects displayed variant prices and catalog invariants, and does not invent variant-specific checkout semantics.
