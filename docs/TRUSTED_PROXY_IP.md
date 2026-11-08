# Authentication throttle identity

Production traffic must use the trusted TLS terminator, then the loopback-only
internal Nginx gateway. On the TLS terminator, overwrite these headers rather
than appending incoming client values:

```nginx
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-Mallbyte-Client-IP $remote_addr;
proxy_set_header Host $host;
```

The internal gateway discards the ordinary incoming X-Forwarded-For and forwards
only X-Mallbyte-Client-IP as a single address. Set AUTH_TRUSTED_PROXY_NETWORKS to
the exact peer IP/CIDR Django sees from this gateway (comma-separated CIDRs;
use /32 or /128 for a fixed address). Never use 0.0.0.0/0 or ::/0. Restrict network
access to the gateway and web listener to trusted infrastructure.

Django auth throttles ignore forwarded addresses from untrusted peers and reject
chains or malformed addresses. The default trusted list is empty. Missing
configuration therefore falls back to the peer, potentially sharing one throttle
bucket; it does not permit clients to invent identities. Verify distinct real
clients and a forged-header negative case on staging before promotion.

Deploy the outer proxy, internal gateway and Django configuration together.
If a CDN precedes the TLS terminator, configure its own trusted real-IP handling
first, so $remote_addr is a verified client address.

Administrative audit logs now use the same canonical trusted-peer address policy
as authentication throttles. Untrusted or chained X-Forwarded-For values cannot
forge an audit client IP. A missing/invalid peer address is stored as NULL in the
audit's nullable IP column; it is never persisted as the throttle's "unknown"
marker.
