# Return and refund integrity

This change is stacked on `fix/p0-private-media` (#25), because it extends that
return migration graph. Apply `returns.0003_refund_amount_precision` before
starting the API/workers. The migration expands monetary precision and adds
approved <= requested constraints. It fails with counts if existing approvals
exceed requested amounts; reconcile those records explicitly, never silently
truncate or rewrite financial history.

Customer return requests reserve the discounted merchandise consideration of
order items. Financial snapshots are authoritative where present. Legacy orders
without snapshots allocate the persisted order discount by the same deterministic
largest-remainder rule used at checkout. Partial or inconsistent snapshots fail
closed for manual reconciliation. Current product prices are irrelevant. Active
claims reserve both item quantity and refundable consideration; rejected and
cancelled claims release those reservations. The final quantity claim receives
any rounding remainder. Duplicate item IDs return HTTP 400 atomically.

The default claim covers merchandise only. Whether to refund shipping/tax is an
explicit policy decision; the existing trusted verified posting service can
account for those components within original charged/approved limits. No external
payment gateway or new money-transfer operation is introduced.

Marking a return refunded always requires exact verified refund evidence,
including when `SETTLEMENTS_LEDGER_ENABLED=False`. Disabling ledger reporting must
not make a status edit count as financial proof. Existing legacy refunds and
unsnapshotted captures need reconciliation through trusted evidence procedures;
the API does not fabricate payment evidence or backfill seller ownership. A
zero-value return needs a separate non-monetary closing policy and cannot be
labelled as a cash refund. Replaying a completed, verified return is idempotent.

A full verified refund updates Payment and Order financial statuses in the same
transaction and writes one order history event. Partial refunds preserve paid
order/payment states and remain visible through append-only refund records.

Return receipt does not automatically put goods back into saleable stock. Product
policy must choose inspection, quarantine, damaged/lost disposition, warehouse
selection and authorization before adding an immutable, idempotent inventory
movement. Replacement/repair/store-credit flows, return windows and paid-order
cancellation remain decisions; receiving or refunding a return must not silently
invent these policies or double-credit inventory.
