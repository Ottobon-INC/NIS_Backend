import ipaddress
import socket
import os
from urllib.parse import urlparse

class SSRError(Exception):
    pass

FORBIDDEN_HOSTNAMES = {
    "localhost", "127.0.0.1", "::1", "0.0.0.0",
    "169.254.169.254", "metadata.google.internal",
    "instance-data"
}

ALLOWED_SCHEMES = {"http", "https"}

def validate_url_security(url: str) -> str:
    """
    Validates URL against Server-Side Request Forgery (SSRF), internal network addresses,
    cloud metadata services, and unsafe protocols.
    """
    if not url or not isinstance(url, str):
        raise SSRError("URL must be a non-empty string")

    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise SSRError(f"Unsupported protocol '{parsed.scheme}'. Only HTTP and HTTPS are permitted.")
    
    hostname = parsed.hostname
    if not hostname:
        raise SSRError("Invalid URL: hostname is missing")
        
    hostname_lower = hostname.lower()
    if hostname_lower in FORBIDDEN_HOSTNAMES or hostname_lower.endswith(".local") or hostname_lower.endswith(".internal"):
        raise SSRError(f"Access to '{hostname}' is blocked for security reasons.")

    # Validate port if specified
    if parsed.port and parsed.port not in [80, 443, 8080, 8443]:
        raise SSRError(f"Access to non-standard port {parsed.port} is blocked.")

    # DNS resolution & IP check (skip during unit tests if ENV=test)
    if os.environ.get("ENV") != "test":
        try:
            # Resolve all IPs
            addr_info = socket.getaddrinfo(hostname, None)
            for item in addr_info:
                ip_str = item[4][0]
                ip_obj = ipaddress.ip_address(ip_str)
                if (
                    ip_obj.is_private
                    or ip_obj.is_loopback
                    or ip_obj.is_link_local
                    or ip_obj.is_multicast
                    or ip_obj.is_reserved
                    or ip_obj.is_unspecified
                ):
                    raise SSRError(f"Access to private/internal IP address '{ip_str}' is forbidden.")
        except socket.gaierror:
            # DNS resolution failed or domain does not exist; let http client handle 404
            pass

    normalized = f"{parsed.scheme.lower()}://{hostname}{parsed.path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    return normalized
