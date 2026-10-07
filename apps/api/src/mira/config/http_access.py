"""Pure explicit private-listener configuration; no DNS, sockets or files."""
from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class PrivateOrigin:
    origin: str
    scheme: str
    authority: str
    hostname: str


def validate_http_access(host: str, port: int, origins: tuple[str, ...],
                         private_network: bool) -> PrivateOrigin | None:
    if type(private_network) is not bool:
        raise ValueError("private_network_boolean_required")
    if not private_network:
        if host not in ("127.0.0.1", "localhost"):
            raise ValueError("loopback_or_explicit_private_network_required")
        return None
    if type(host) is not str or "%" in host:
        raise ValueError("private_literal_bind_required")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("private_literal_bind_required") from None
    networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
    if not any(address in ipaddress.ip_network(network) for network in networks):
        raise ValueError("private_literal_bind_required")
    if type(port) is not int or not 1024 <= port <= 65535 or len(origins) != 1:
        raise ValueError("one_exact_private_origin_required")
    origin = origins[0]
    if type(origin) is not str or not origin.isascii() or len(origin) > 255:
        raise ValueError("private_origin_invalid")
    try:
        parsed = urlsplit(origin)
        hostname = parsed.hostname
        if (parsed.scheme not in ("http", "https") or not hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment
                or parsed.netloc != parsed.netloc.lower() or parsed.port != port
                or any(ord(c) < 0x21 or ord(c) > 0x7e for c in origin)):
            raise ValueError("private_origin_invalid")
        try:
            origin_address = ipaddress.ip_address(hostname)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*", hostname):
                raise ValueError("private_origin_invalid") from None
            if hostname == "localhost" or hostname.endswith(".localhost"):
                raise ValueError("private_origin_invalid")
        else:
            if origin_address != address:
                raise ValueError("private_origin_must_match_bind")
        authority = (f"[{hostname}]" if ":" in hostname else hostname) + f":{port}"
        if origin != parsed.scheme + "://" + authority:
            raise ValueError("private_origin_invalid")
        return PrivateOrigin(origin, parsed.scheme, authority, hostname)
    except ValueError:
        raise ValueError("private_origin_invalid") from None
