# Commerce business permissions

This PR is stacked on `fix/p0-rbac-permissions` (#33), which seeds the permissions
and repairs permission-cache invalidation. Apply `rbac.0014` first. Django
`is_staff` grants access to Django administration subject to its model permissions;
it no longer grants cross-customer commerce API access.

| Domain | Cross-customer read | Management |
| --- | --- | --- |
| Orders | `view_all_orders` | `manage_orders` |
| Payments | `view_all_payments` | `manage_payments` |
| Shipments | `view_all_shipments` | `manage_shipments` |
| Returns | `view_all_returns` | `manage_returns` |

Management includes the read access needed for that domain. Read access alone
cannot cancel another customer's order/payment, advance fulfillment, approve a
return, or mark it refunded. Return business services and payment/shipment input
serializers also enforce these boundaries. Authenticated owners retain their
existing customer operations. The disabled mock-capture setting stays effective.

Superusers retain access. No arbitrary staff accounts receive new business grants.
Before rollout, explicitly review operational roles and grant the permissions they
need through the existing role-assignment interface. Product-admin membership
alone no longer grants order-status management. Frontends should obtain their
capabilities from the permissions endpoint rather than infer access from staff.

Order `admin_note` and raw payment gateway/event metadata are returned only to
users authorized to read across customers in that domain. Ordinary owners still
receive payment status, amounts, references and safe event summaries. Nested event
serializers receive the same request context, including create/action responses.

This is independent of gateway integration. No production records or role grants
are rewritten automatically. The private-media PR must allow the corresponding
return-management capability at its authenticated download boundary too.
