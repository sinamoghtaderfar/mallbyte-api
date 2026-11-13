# Cancelling stale parcels after an order closes

Cancelling a seller parcel previously reset its fulfillment to `paid` and
recalculated the aggregate order status unconditionally. A stale non-delivered
parcel attached to a refunded, cancelled, already delivered or unpaid order could
therefore change that order back to `paid` while its financial state remained
unchanged. For example, `refunded/refunded` became `paid/refunded`.

Parcel cancellation remains available to stop such a stale parcel. It still
writes the cancellation timestamp, shipment event and configured notification.
Seller fulfillment and aggregate order statuses are recalculated only while the
locked order has a paid payment state and an active `paid`, `processing` or
`shipped` order state. Completed fulfillment snapshots and delivery timestamps
are preserved for other order states. Existing restrictions on delivered parcels
and duplicate cancellation remain in effect.

The fix depends on PR #45 for transaction and notification rollback guarantees.
It requires no migration, changes no refund approval or restocking policy, and
performs no external payment operation. It does not attempt to repair historical
contradictions automatically; reconcile those against financial and shipment
history before changing stored order states.

Regression tests reproduce the five inconsistent transitions before the change
and verify that normal paid-order cancellation and duplicate rejection continue
to work. Terminal-state fixtures represent a stale legacy parcel rather than
claiming that the normal delivered-return workflow creates such parcels.
