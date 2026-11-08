# Explicit inventory restoration for received returns

An authorized manager can explicitly restore inspected, sellable units. Receiving
a return or refunding money never restores stock automatically. No gateway or
quarantine/disposal policy is introduced.

After applying `returns.0004`, deliberately grant the business permission
`restock_returns` (module `inventory`) to selected managers. The migration creates
the permission and grants it to no role. Plain Django staff, sellers, customers
and users with only `manage_returns` do not acquire this power. Include the RBAC
hardening PR #33 before staging to ensure immediate revocation of role grants.

POST `/api/returns/requests/{request_id}/items/{item_id}/restock/`:

```json
{
  "warehouse": 12,
  "quantity": 1,
  "idempotency_key": "unique-inspection-operation-key",
  "sellable_confirmed": true,
  "note": "Inspected and confirmed sellable."
}
```

The destination must be an explicit active warehouse. Physical receipt requires
the return shipment's recorded `received_at`, an appropriate received/accepted
item state and a return that has reached receipt. A financial `refunded` status
alone is insufficient. Existing legacy returns without reliable physical receipt
records require explicit investigation; the migration backfills no stock.

The manager chooses a positive quantity up to the un-restored received quantity.
Partial operations may use different keys, but their total cannot exceed the
received item's quantity. The operation locks Order -> Return -> ReturnItem ->
Warehouse -> Stock and creates one inventory RETURN movement with an append-only
audit record containing the actor, time, chosen warehouse, quantity and note.
Both records and the stock change commit or roll back together. Historical audit
relations protect the warehouse, item and movement from deletion.

The response returns the audit ID, movement ID and remaining quantity. A repeated
key with identical details returns the existing movement (HTTP200); a changed
quantity, warehouse or note with that key returns409. New operations return201.
Retry an uncertain request with the same key; never generate a new key solely
because a response was lost. Payment, refund, ledger and order state do not change.

Frontend: expose this as a deliberate manager operation after physical inspection,
require a sellability confirmation, explicit warehouse and quantity, and retain
the idempotency key across retries. Damaged or unconfirmed items must remain out
of this sellable-stock operation.

Schema rollback does not undo a physical restock: its inventory movement and
quantity remain. Prefer a forward fix; preserve the audit/idempotency history
and reconcile inventory before considering a migration rollback. No automatic
backfill or reversal of historical stock is performed by this migration.
