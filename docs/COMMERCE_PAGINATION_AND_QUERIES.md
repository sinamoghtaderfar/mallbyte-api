# Commerce pagination and query behavior

This change is stacked on `fix/p0-commerce-permissions` (#39). No new migration
is required. Apply the dependency migrations before deploying this API version.

Two formerly unbounded collection actions now return the standard pagination
object (`count`, `next`, `previous`, `results`):

- `GET /api/orders/orders/seller/`
- `GET /api/shipping/shipments/eligible-orders/`

Frontends must read rows from `results` and follow `next`; the default page size
is 20 and `page_size` is capped at 100. Existing customer, manager and seller
ownership boundaries remain enforced.

Shipment eligibility is filtered in SQL before counting/slicing. A multi-seller
order stays eligible while any seller has paid/processing items and no active
shipment. Existing item-less orders keep the legacy one-active-shipment rule.
Cancelled/returned shipments do not permanently hide eligible orders.

Seller summaries/detail reuse the current seller's prefetched items and
fulfillment; they do not query each fulfillment twice or load another seller's
items into the response. Cart responses batch product and available inventory
reads. Order counts use an aggregate instead of loading every historical item.
Detail/action responses load event authors and return attachment/history authors
in batches, including when an action returns a freshly changed object.

Return creation accepts 1–100 distinct item entries (the refund-consistency PR
also rejects duplicates atomically). Oversized/empty arrays return HTTP 400
before executing the business workflow.

Regression tests compare database query counts for one versus several records,
check stable page boundaries, verify eligibility is filtered before pagination,
and preserve seller isolation and multi-seller shipping behavior. These checks
bound query growth, not production latency; production query plans and index
selectivity must still be monitored with realistic staging data.
