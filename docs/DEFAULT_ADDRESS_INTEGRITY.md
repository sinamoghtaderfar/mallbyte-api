# Default address consistency

At most one address per user may be the default. Having no default is supported;
deleting or explicitly clearing a default does not automatically choose a new
address on the customer's behalf.

Promoting a default locks its owner row before clearing the previous default and
saving the new one in a single transaction. This serializes simultaneous first
promotions even when no default row exists. A partial unique database constraint
also protects writes that bypass the model. An unsuccessful save rolls the
previous default back.

A metadata save from a previously loaded address does not rewrite an unchanged
`is_default` or owner value. It therefore cannot reinstate an old default after
another request promoted a different address. Explicit `is_default` changes and
`save(update_fields=["is_default"])` continue to promote/clear defaults. The API's
`set_default` action delegates to this transaction instead of clearing the old
default before it.

Migration `accounts.0018_default_address_constraint` depends on the identity
workflow migration `0017`. Its preflight refuses existing duplicate defaults
without choosing or modifying customer addresses. Before rollout, inspect any
reported duplicate groups using a read-only aggregate, then deliberately select
the intended default per affected user through an approved data-repair process.
Rerun migration only after that review. Do not bypass the constraint or silently
discard addresses. No frontend response change is needed.
