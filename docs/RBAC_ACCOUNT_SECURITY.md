# Account management authorization and seller decisions

`is_staff` controls entry to Django admin and the existing privileged-login MFA
flow. It does not grant business API capabilities. The seller admin endpoints now
require `view_sellers`, `approve_seller`, or `reject_seller`; account deletion
requires `delete_user`. Superusers retain access. A delegated account deleter
cannot delete staff accounts, superusers, or itself.

Migration `rbac.0014_account_management_permissions` seeds these codenames and the
commerce capabilities (`view_all_orders`/`manage_orders`,
`view_all_payments`/`manage_payments`, `view_all_shipments`/`manage_shipments`, and
`view_all_returns`/`manage_returns`). It preserves existing explicit grants and
adds only the three seller capabilities to an existing `vendor_manager` role.
No permission is granted based on the staff flag. Commerce enforcement is a
separate dependent change; applying the seed alone does not change those APIs.
After deployment, a superuser should review role assignments and deliberately
grant account deletion to authorized operators. The frontend should use the
permissions endpoint to show available seller/account actions; a staff flag is
not sufficient.

Business authorization reads current permissions through a single DISTINCT query
instead of a shared result cache. This makes role revocation, role reassignment,
permission rename, expiration, and rolled-back grants visible without a cache
invalidation window. Old cache entries are ignored. The compatibility cache
clear helpers remain for callers from older releases. Normal transaction
isolation applies: an authorization check observes its database statement's
snapshot. No Redis cache availability is required for RBAC decisions.

Seller approval/rejection obtains locks in `User -> Seller` order, validates the
pending state again under the lock, and commits seller status, user seller flag,
and the vendor role together. This matches checkout's seller lock order.
`NO KEY UPDATE` permits concurrent foreign-key references. Missing vendor role
configuration is a validation error and changes no state; operators must restore
the intended existing vendor role/permissions rather than approve a partially
configured seller. Repeated or competing decisions cannot overwrite a completed
application. Rejection requires a nonblank reason of 3–2000 characters.

Django review moderator actions preserve superuser status and do not reactivate
suspended accounts. Removing the moderator group also clears staff access when
no other Django admin permission remains. Existing independent admin permissions
preserve staff access. System role permission changes are consistently denied by
both role-management APIs; seeded system policy is changed through reviewed
migrations. Custom roles remain editable by superusers.

Seller application creation also locks the owner before checking for an existing
profile and inserting the application. Concurrent applications by one user return
one success and one HTTP 400. Store name/slug uniqueness races between different
users return a sanitized validation error; other database integrity failures are
not mislabeled as validation errors.
