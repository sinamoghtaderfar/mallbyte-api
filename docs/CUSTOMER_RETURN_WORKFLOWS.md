# Customer return submissions

Requires the private-media PR first. Existing return eligibility and moderation
rules remain authoritative; these endpoints do not authorize refunds or restock.

- POST `/api/returns/requests/{id}/attachments/` with multipart `file`, optional
  `return_item`, `attachment_type`, `caption`. Only the claim owner may submit;
  the item must belong to that claim. Uses the support upload content/size policy,
  private storage, generated filenames and an authenticated download URL. Closed,
  rejected, cancelled, refunded or replaced claims cannot receive new evidence.
- POST `/api/returns/requests/{id}/shipment/` with `carrier`, `tracking_number`
  and optional HTTPS `tracking_url`, after approval. Timestamps and owner are
  server-controlled. Exact repeats are idempotent; changed tracking after
  submission requires support correction. Receiving the item remains privileged.

Frontend should upload via authenticated multipart requests, consume structured
400/404/409 errors, and fetch sensitive downloads with authenticated requests.
No migration is required beyond the private-media PR.
