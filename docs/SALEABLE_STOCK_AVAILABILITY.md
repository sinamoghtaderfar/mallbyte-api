# Physical and saleable stock

`stock`/`total_stock` and `reserved_stock` retain their physical totals across all
warehouses, including deactivated warehouses. `available_stock` and `is_in_stock`
now use only unreserved stock in active warehouses, matching checkout's existing
warehouse eligibility rule. Clients should use `available_stock` for purchase
availability instead of subtracting the physical totals themselves.

Catalog list/detail/comparison projections share a filtered availability aggregate
and the in-stock filter uses an active-warehouse EXISTS query. This keeps inactive
stock visible in physical inventory without advertising it for checkout, and does
not add a query per catalog item. No migration or stock data rewrite is required.

This change does not define a quarantine/disposition workflow. Warehouse
deactivation is an operational eligibility flag, not a substitute for inspecting
returned goods or recording an authorized, idempotent return inventory movement.
Reservations and historical stock in inactive warehouses are not released or
transferred automatically. Split-warehouse fulfillment remains a separate policy.
