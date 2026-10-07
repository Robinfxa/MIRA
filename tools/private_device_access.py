"""Explicit private launch declarations. No DNS, secrets or sockets on check."""
from dataclasses import dataclass
import os
from pathlib import Path
import stat

from mira.config.http_access import PrivateOrigin, validate_http_access


class PrivateDeviceError(ValueError):
    """Public fixed recovery text; never includes credential or path contents."""


@dataclass(frozen=True, slots=True)
class PrivateDeviceOptions:
    host: str
    port: int
    policy: PrivateOrigin
    pairing_directory: Path | None
    certificate: Path | None
    private_key: Path | None
    trusted_no_pairing: bool = False
    loopback_port: int | None = None
    max_devices: int = 2

    def http_settings(self) -> dict:
        return {"host": self.host, "port": self.port, "private_network": True,
                "allowed_origins": (self.policy.origin,)}

    def declaration(self) -> dict:
        return {"enabled": True, "scheme": self.policy.scheme, "origin": self.policy.origin,
                "max_device_sessions": self.max_devices, "pairing_required": not self.trusted_no_pairing,
                "access_mode": "trusted_private_network_no_pairing" if self.trusted_no_pairing else "one_use_pairing", "pairing_files_created": False,
                "listener_started": False, "browser_tls_trust": "not_verified",
                "microphone_secure_context_required": True,
                "persistence_mode": "ephemeral_sessions_only",
                "local_origin": f"http://127.0.0.1:{self.loopback_port}" if self.loopback_port else None}


def add_device_arguments(parser) -> None:
    parser.add_argument("--loopback-only", action="store_true", help="serve only on this computer; disable default trusted Wi-Fi access")
    parser.add_argument("--require-device-pairing", action="store_true", help="require the two existing one-use code files for private access")
    parser.add_argument("--trusted-private-network-no-pairing", action="store_true",
        help="trust anyone who can reach the private origin to use enabled service quotas; up to 16 ephemeral browser sessions, no code files")
    parser.add_argument("--private-bind", help="explicit private IPv4/ULA IPv6 address; never wildcard/public")
    parser.add_argument("--device-origin", help="one exact URL used by both devices, including explicit port")
    parser.add_argument("--device-pairing-dir", type=Path,
        help="existing owner-only directory outside checkout; serve creates two one-use code files")
    parser.add_argument("--tls-cert-file", type=Path, help="existing certificate for the exact device origin")
    parser.add_argument("--tls-key-file", type=Path, help="existing owner-only TLS key; never printed")
    parser.add_argument("--allow-private-http-text", action="store_true",
        help="acknowledge plaintext on the private LAN for text-only testing; voice requires trusted HTTPS")


def _tls_metadata(path: Path, *, private: bool) -> Path:
    if not isinstance(path, Path) or not path.expanduser().is_absolute():
        raise PrivateDeviceError("TLS certificate and key require absolute existing local file paths.")
    path = path.expanduser().absolute()
    try:
        info = path.lstat()
    except OSError:
        raise PrivateDeviceError("TLS certificate or key file is missing or unavailable.") from None
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise PrivateDeviceError("TLS certificate and key must be regular files, not symbolic links.")
    if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise PrivateDeviceError("TLS private key must be an owner-only file; its contents were not read.")
    return path


def device_options(args) -> PrivateDeviceOptions | None:
    trusted = getattr(args, "trusted_private_network_no_pairing", False)
    required = getattr(args, "require_device_pairing", False)
    dual = getattr(args, "_dual_listener", False)
    values = (args.private_bind, args.device_origin, args.device_pairing_dir,
              args.tls_cert_file, args.tls_key_file)
    if getattr(args, "loopback_only", False):
        if any(value is not None for value in values) or trusted or required or args.allow_private_http_text:
            raise PrivateDeviceError("--loopback-only cannot be combined with private network options.")
        return None
    if args.private_bind is not None and args.device_origin is None and not any(
            value is not None for value in (args.device_pairing_dir, args.tls_cert_file, args.tls_key_file)) and not required:
        if any(getattr(args, field, None) is not None for field in ("memory_db", "story_db", "conversation_db")):
            raise PrivateDeviceError("Private network access cannot be combined with persistent memory/history.")
        _default_origin(args.private_bind, args.port)
        return None  # serve resolves the exact dual-listener policy before constructing providers.
    if all(value is None for value in values) and not args.allow_private_http_text and not trusted and not required:
        return None
    if trusted and required:
        raise PrivateDeviceError("Choose trusted access or required device pairing, not both.")
    if not trusted and not required and args.device_pairing_dir is None and args.private_bind is not None:
        trusted = True
    if trusted and args.device_pairing_dir is not None:
        raise PrivateDeviceError("Trusted private network mode needs no pairing directory; omit --device-pairing-dir.")
    if any(value is None for value in values[:2]):
        raise PrivateDeviceError("Private device access needs --private-bind and --device-origin.")
    if not trusted and args.device_pairing_dir is None:
        raise PrivateDeviceError("Private device access needs --device-pairing-dir unless --trusted-private-network-no-pairing is explicitly selected.")
    if any(getattr(args, field, None) is not None for field in ("memory_db", "story_db", "conversation_db")):
        raise PrivateDeviceError("Private two-device mode supports independent ephemeral sessions only; persistent memory/history stays single-operator.")
    if args.create_local_operator_pairing:
        raise PrivateDeviceError("Private device mode creates two separate codes; omit the single-operator pairing flag.")
    try:
        policy = validate_http_access(args.private_bind, args.port, (args.device_origin,), True)
    except ValueError:
        raise PrivateDeviceError("Choose one explicit private bind address and exact HTTP/HTTPS origin using the same port.") from None
    directory = None
    if not trusted:
        directory = args.device_pairing_dir.expanduser()
        if not directory.is_absolute() or ".." in directory.parts:
            raise PrivateDeviceError("Device pairing directory must be an absolute existing private directory outside the checkout.")
        root = Path(__file__).resolve().parents[1]
        try:
            info = directory.lstat()
            if (directory == root or root in directory.parents or directory.resolve() != directory
                    or not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
                raise PrivateDeviceError("Device pairing directory must be owner-only, existing, and outside the checkout.")
        except OSError:
            raise PrivateDeviceError("Device pairing directory must be owner-only, existing, and outside the checkout.") from None
    certificate = key = None
    if policy.scheme == "https":
        if args.tls_cert_file is None or args.tls_key_file is None:
            raise PrivateDeviceError("HTTPS needs both an existing certificate and key for the configured origin.")
        if args.allow_private_http_text:
            raise PrivateDeviceError("The plaintext acknowledgement applies only to an HTTP text-only origin.")
        certificate = _tls_metadata(args.tls_cert_file, private=False)
        key = _tls_metadata(args.tls_key_file, private=True)
    else:
        if args.voice and not dual:
            raise PrivateDeviceError("Phone microphone access requires trusted HTTPS; private HTTP supports text only.")
        if args.tls_cert_file is not None or args.tls_key_file is not None:
            raise PrivateDeviceError("TLS files require an HTTPS device origin.")
        if not args.allow_private_http_text and not dual:
            raise PrivateDeviceError("Private HTTP is plaintext; explicitly select --allow-private-http-text for text-only testing.")
    return PrivateDeviceOptions(args.private_bind, args.port, policy, directory, certificate, key, trusted, args.port if dual else None, 16 if trusted else 2)


def create_device_pairing(options: PrivateDeviceOptions, *, checkout_root: Path):
    if options.trusted_no_pairing:
        from mira.entrypoints.http.trusted_device_access import TrustedDeviceAccess
        origins = (options.policy.origin,)
        if options.loopback_port is not None:
            origins += (f"http://127.0.0.1:{options.loopback_port}", f"http://localhost:{options.loopback_port}")
        return TrustedDeviceAccess(origins, max_devices=options.max_devices), ()
    from tools.operator_pairing_file import create_pairing_material
    from mira.entrypoints.http.device_pairing import DevicePairing
    materials = tuple(create_pairing_material(options.pairing_directory, checkout_root=checkout_root)
                      for _ in range(2))
    pairing = DevicePairing(tuple(material.code for material in materials), (options.policy.origin,))
    return pairing, tuple(material.path for material in materials)


def _default_origin(host: str, port: int) -> str:
    import ipaddress
    try:
        address = ipaddress.ip_address(host)
        origin = f"http://[{address}]:{port}" if address.version == 6 else f"http://{address}:{port}"
        validate_http_access(str(address), port, (origin,), True)
        return origin
    except ValueError:
        raise PrivateDeviceError("Choose an explicit RFC1918 or ULA private address; wildcard/public binds are not allowed.") from None


def default_lan_requested(args) -> bool:
    return (not getattr(args, "loopback_only", False)
        and not any(getattr(args, field, None) is not None for field in ("memory_db", "story_db", "conversation_db"))
        and args.device_origin is None and args.device_pairing_dir is None
        and args.tls_cert_file is None and args.tls_key_file is None
        and not getattr(args, "require_device_pairing", False))


def resolve_serve_access(args) -> PrivateDeviceOptions | None:
    if default_lan_requested(args):
        if args.private_bind is None:
            from tools.lan_discovery import discover_lan_address
            found = discover_lan_address()
            if found.address is None:
                import sys
                candidates = ", ".join(found.candidates) if found.candidates else "无"
                print("WARNING: 局域网未启用，仅本机。自动选择结果："+found.reason+
                    "；候选私网地址："+candidates+"。需要局域网时，追加 --private-bind 你的明确私网IP；"
                    "也可用 --loopback-only 保持仅本机。", file=sys.stderr, flush=True)
                return None
            args.private_bind = found.address
        args.device_origin = _default_origin(args.private_bind, args.port)
        args.trusted_private_network_no_pairing = True
        args.allow_private_http_text = True
        args._dual_listener = True
    return device_options(args)


def run_private_server(app, options: PrivateDeviceOptions) -> None:
    import uvicorn
    if options.loopback_port is not None:
        import socket
        sockets = []
        try:
            for host in ("127.0.0.1", options.host):
                sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
                sockets.append(sock)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if ":" in host:
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                sock.bind((host, options.port))
                sock.listen(128)
                sock.setblocking(False)
            config = uvicorn.Config(app, host=options.host, port=options.port, workers=1,
                access_log=False, proxy_headers=False, ws_max_size=32768, ws_max_queue=8)
            uvicorn.Server(config).run(sockets=sockets)
        finally:
            for sock in sockets:
                sock.close()
        return
    uvicorn.run(app, host=options.host, port=options.port, workers=1, access_log=False,
        proxy_headers=False, ws_max_size=32768, ws_max_queue=8,
        ssl_certfile=str(options.certificate) if options.certificate is not None else None,
        ssl_keyfile=str(options.private_key) if options.private_key is not None else None)
