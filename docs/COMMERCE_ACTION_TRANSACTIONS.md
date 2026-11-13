# Atomic commerce action records

This PR is stacked on the commerce-authorization PR (#39). No migration or
external payment gateway change is required.

Payment success/failure/cancellation and shipment creation/state actions now keep
model state, database audit events and in-app notifications in the same outer
transaction. A database/notification failure rolls the whole action back, leaving
the prior state available for a safe retry. Previously model helpers committed
before view-level events/notifications were inserted, so a failed response could
leave committed state with missing audit/notification records.

The existing model-level row locks and validation remain active. In-app
notification writes are database-only and notification preferences still apply.
No external network operation or money transfer is executed in the transaction.
If asynchronous delivery is added later, enqueue it after commit or through a
transactional outbox.

Regression tests inject failures at notification and audit boundaries and verify
payment, order, inventory, shipment, seller fulfillment and history rollback.
