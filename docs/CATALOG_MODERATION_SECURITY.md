# Catalog and review moderation contract

Seller changes to product content, images or variants return the product to
`pending` and clear the previous approval. The storefront hides it until a
product administrator approves it again. Parent and component edits serialize
with moderation on the product row. Only product administrators may change the
featured flag; the seller serializer treats `is_featured` as read-only.

Customers changing approved review rating, title or comment return that review
to `pending`; product rating aggregates are refreshed in the same transaction.
Review product/customer identity is immutable. Review moderation requires the
existing Django `reviews.change_productreview` permission (including the Review
Moderators group), superuser authority, or explicit `moderate_reviews` RBAC
permission. An unrelated `is_staff` flag grants no review moderation access.

Public product details omit `cost_per_item` and seller login `seller_email`.
Owners and product administrators retain these fields. Wishlist creates/updates
accept only active approved products; existing unpublished items are hidden and
adding the same public product repeatedly is idempotent.

Frontend changes: make cost/email fields optional in public product responses,
disable seller featured controls, show the new pending state after seller/review
edits, and avoid assuming an unpublished wishlist item remains visible. API
paths and successful response envelopes remain unchanged.
