# Django admin authorization boundaries

Production already disables the password/session-based Django admin route with
`DJANGO_ADMIN_ENABLED = False` in production settings. API staff/superuser login
continues to use the existing MFA flow. This change does not add a separate MFA
interface or enable Django admin in production.

When Django admin is enabled for development or controlled operations, delegated
Django `add/change/delete` model permissions no longer grant authority to mutate
users, authentication groups, business roles, business permissions, role grants,
or user-role assignments. Only active superusers can mutate these policy-bearing
models. A delegated `change_user` permission therefore cannot reset a superuser's
password or edit superuser/group/permission flags. Explicit Django view permissions
continue to permit read-only access; existing business API permissions remain
independent of these Django admin permissions.

OTP challenge contents are visible only to superusers and remain read-only.
Admin action logs remain viewable to authorized readers but cannot be created,
edited, or deleted through Django admin, including by a superuser. Normal backend
services still create their audit records.

Review existing delegated grants before enabling Django admin. Staff who previously
used these administrative mutation pages must use the constrained business APIs
or an explicitly authorized superuser workflow. No schema or frontend API change
is required. Merge after the account/RBAC security PR.
