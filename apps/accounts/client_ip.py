"""Use a single, proxy-sanitized client address only from configured peers."""
from ipaddress import ip_address, ip_network

from django.conf import settings


def client_ip(request):
    peer = request.META.get("REMOTE_ADDR", "")
    try:
        address = ip_address(peer)
    except ValueError:
        return "unknown"
    trusted = any(
        address in ip_network(network)
        for network in getattr(settings, "AUTH_TRUSTED_PROXY_NETWORKS", [])
    )
    if trusted:
        # The outer TLS terminator overwrites X-Mallbyte-Client-IP. The internal
        # gateway forwards that one address as XFF, never an appended chain.
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").strip()
        try:
            return str(ip_address(forwarded))
        except ValueError:
            pass
    return str(address)
