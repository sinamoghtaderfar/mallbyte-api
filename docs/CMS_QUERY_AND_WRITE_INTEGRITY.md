# CMS query and write integrity

This patch depends on the repository quality PR (which in turn depends on observability quality). It fixes the CMS portions of audit findings 26, 29 and 42 and closes a publication-state race found during the final bounded QA pass.

FAQ/category and navigation-item/menu numeric query filters now validate positive signed-64-bit IDs and return field-specific HTTP 400 errors for malformed, fractional, negative or overflowing values. Existing valid filters and response envelopes remain compatible.

FAQ category lists reuse one prefetched item query and filter hidden rows without invalidating the cache. Navigation menu/item lists fetch visible related items, pages, menu and parent references in bounded queries and serialize the documented two-level tree without per-item queries. Existing guest/authenticated/draft-viewer visibility rules remain authoritative. Moving a root that still has children underneath another root is rejected, because that would create an unsupported third level.

Homepage sections retain their existing JSON shape but each collection is bounded to 20 items by default. Operators can set `CMS_HOMEPAGE_ITEM_LIMIT` (clamped to 1–100); full collections remain available through their dedicated paginated endpoints. Frontends needing more homepage cards should explicitly configure the limit or use those paginated endpoints.

CMS mutations now acquire a row lock before checking object-level permissions that depend on current publication state. An editor racing a publisher waits for the publisher's transaction, then receives HTTP 403 for already-published content; a stale draft instance cannot overwrite the approved body or publication status. Publish/archive/edit/delete use the same row lock. Explicit duplicate page slugs validate normally, and unexpected uniqueness/constraint races roll back the whole mutation and return a sanitized validation error rather than HTTP 500.

No database migration is required. Regression tests cover malformed numeric filters, query bounds and hidden related objects, homepage limits, explicit slug conflicts, unsupported hierarchy moves and PostgreSQL publication/edit concurrency. This change does not change editorial roles, add HTML rendering, or introduce an automatic content approval policy.
