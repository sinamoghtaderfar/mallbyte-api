# Support transaction and collection behavior

All detail mutations (reply, status changes, assignment, priority, tags and
attachment uploads) now acquire the ticket row lock in one transaction. The
status checked by a reply/upload is current under that lock, so a concurrent
close cannot be overwritten by a reply that read an older open status. Message,
audit, status and notification database writes commit together. If audit creation
fails after an attachment storage write, that new file is removed. Row locking
uses `NO KEY UPDATE OF self` to avoid locking nullable joins and to permit
foreign-key references. Existing permission/object ownership checks run on the
locked ticket.

Repeated close/resolve/reopen requests for the current state return its existing
representation without duplicate audit/notification writes or timestamp changes.
A public reply that reopens a resolved ticket clears its obsolete resolution
and closure timestamps. Existing supported state-change policy otherwise stays
in place; this change does not introduce a new customer reopen permission.

Ticket representations retain the `messages` and `attachments` arrays, bounded to
50 entries each. Messages contain the latest 50 visible messages in chronological
order; attachments contain the latest 50. New booleans `messages_truncated` and
`attachments_truncated` tell clients that more history exists. Internal-note
filtering occurs in the database before the limit is applied. Related senders,
uploaders and tags are prefetched; list query count does not grow per ticket.

Use `GET /api/support/tickets/{id}/messages/` for the full permission-filtered
history in the standard paginated `{count,next,previous,results}` format.
Attachments, audit-log and agent collection endpoints retain their array response
body and now return a bounded page. Their `X-Total-Count` and RFC-style `Link`
headers expose the total and next/previous page URLs. Frontends must follow the
`Link` header instead of assuming one array contains the entire collection.
Agent eligibility is evaluated by database `EXISTS` predicates rather than
loading every user and querying their roles separately. Numeric ticket filters
return HTTP 400 for invalid IDs rather than leaking ORM conversion errors.

Deploy after the account/RBAC security change. The old shared permission cache
can otherwise preserve privileges across independent requests or reused user IDs;
these support changes do not duplicate that authorization fix. No support schema
migration is required.
