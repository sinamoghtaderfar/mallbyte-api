# Checkout integrity and deployment

This change depends on `fix/p0-stock-concurrency` (inventory history protection).
Apply the order migrations before deploying the API and workers.

- Checkout locks cart, items, products, seller accounts, seller profiles, then
  stock in a deterministic order. Product/account eligibility locks use PostgreSQL
  `FOR NO KEY UPDATE`, allowing concurrent movement/notification foreign-key
  checks to complete. Capture and cancellation acquire stock in product/warehouse
  order, including for historical orders.
- All cart mutations and checkout use the same cart row lock. Checkout reads its
  item snapshot, sale eligibility and totals after acquiring that lock.
- Clients should send a unique `Idempotency-Key` header (8–128 characters) per
  checkout intent. The optional `idempotency_key` body field is equivalent. A
  replay with the same details returns the original order, even after its cart
  was cleared; a different payload with the same key is rejected. Generate a
  new key when intentionally creating another order.
- `CHECKOUT_SHIPPING_COST` is a trusted nonnegative integer amount in the
  existing order currency. Its default is zero, preserving the existing default
  tariff. Omit `shipping_cost` from client requests; an explicit amount must
  equal the server amount. Configuring zones, carrier quotes and tax rules
  requires a separate product decision.
- Products and their seller account/profile must still be active and approved
  at checkout. Existing inconsistent seller/profile data must be reviewed; the
  change does not automatically approve accounts or alter historical ownership.
- `ORDER_RESERVATION_TTL_SECONDS` defaults to 1800 (minimum 60). Celery Beat runs
  `apps.orders.tasks.expire_pending_orders` every minute and releases up to 100
  expired pending orders per invocation through locked cancellation. Monitor
  worker/Beat availability and tune the batch/schedule to backlog size. Payment
  creation and capture refuse an expired hold even before the cleanup job runs.
  Order detail responses expose `reservation_expires_at` for the client countdown.
- If evidence of an actual money capture arrives after the reservation expired,
  do not retry capture against the released stock or silently recreate the order.
  The capture guard rejects the expired hold to prevent overselling. An operator
  must reconcile the recorded transfer and arrange a refund or a separately
  authorized new order; expiry itself does not reverse a real money transfer.
- Historical orders with a NULL reservation deadline are intentionally left
  untouched: an operator must review and explicitly cancel stale unpaid orders
  rather than infer which stock is reserved from legacy data.

Return windows, paid-order cancellation, replacement/store credit, returned-item
quarantine/disposition, variants and split-warehouse fulfillment remain explicit
product decisions. This change does not invent these policies or a payment
gateway integration.
