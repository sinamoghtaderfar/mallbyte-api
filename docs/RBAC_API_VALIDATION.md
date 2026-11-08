# RBAC API identifier validation and role query cost

This change depends on the account/RBAC authorization fix in PR #33. It does not
grant new permissions or relax the superuser-only boundary of management APIs.

RBAC ID filters and custom role-assignment/permission input serializers now accept
one positive signed-bigint ID, as a JSON integer or decimal integer string.
Booleans, arrays, objects, fractional values, zero, negative IDs and values above
`2**63 - 1` produce field-level HTTP 400 responses before ORM queries.

`user_id`/`role_id` filters on user-role lists and `admin_id`/`target_user` filters
on admin logs are validated explicitly. Repeated recognized query parameters are
rejected rather than silently selecting the last. The `is_active` filter uses
Boolean validation; misspelled values no longer silently mean false. The console
permission mutation continues requiring an actual JSON Boolean for `enabled`.

Role serialization reuses prefetched permission links for both the names and the
count. Paginated role lists and the existing console catalog therefore have a
constant query count as the number of roles grows. Existing response envelopes,
field names, permission policy and successful valid-ID behavior remain intact.

No database migration or frontend response-shape change is required. Clients that
previously submitted ambiguous or malformed filters must correct those inputs.
