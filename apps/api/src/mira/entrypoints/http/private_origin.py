"""Exact authority and CSRF boundary for an explicitly private listener."""
from starlette.responses import JSONResponse

from mira.config.http_access import PrivateOrigin


class PrivateOriginBoundary:
    def __init__(self, app, *, policy: PrivateOrigin):
        self.app = app
        self.policy = policy

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = scope.get("headers", ())
        hosts = [value for name, value in headers if name.lower() == b"host"]
        origins = [value for name, value in headers if name.lower() == b"origin"]
        scheme = {"ws": "http", "wss": "https"}.get(scope.get("scheme"), scope.get("scheme"))
        expected_host = self.policy.authority.encode("ascii")
        expected_origin = self.policy.origin.encode("ascii")
        needs_origin = kind == "websocket" or scope.get("method") not in ("GET", "HEAD", "OPTIONS")
        valid = (len(hosts) == 1 and hosts[0].lower() == expected_host
                 and len(origins) <= 1 and (not origins or origins[0] == expected_origin)
                 and (not needs_origin or len(origins) == 1) and scheme == self.policy.scheme)
        if not valid:
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 4403})
            else:
                await JSONResponse({"code": "private_origin_denied", "message": "Use the configured private service origin."},
                                   status_code=403, headers={"Cache-Control": "no-store"})(scope, receive, send)
            return
        voice_allowed = self.policy.scheme == "https"
        scope.setdefault('state', {})['mira_voice_allowed'] = voice_allowed
        parts = scope.get('path', '').split('/')
        media_route = (len(parts) > 5 and parts[1:4] == ['api', 'v1', 'sessions']
            and parts[5] in {'speech', 'microphone', 'continuous-listening', 'audio-progress', 'response-preference'})
        if not voice_allowed and media_route:
            if kind == 'websocket':
                await send({'type': 'websocket.close', 'code': 4403})
            else:
                await JSONResponse({'code':'private_http_text_only','message':'LAN HTTP supports text only; voice requires local access or trusted HTTPS.'},
                    status_code=403, headers={'Cache-Control':'no-store'})(scope,receive,send)
            return
        await self.app(scope, receive, send)


class DualListenerBoundary:
    """Trust the accepting socket, never a client-selected Host or proxy header."""
    def __init__(self, app, *, private_policy: PrivateOrigin, private_bind: str, port: int):
        self.app = app
        self.private_policy = private_policy
        self.private_bind = private_bind
        self.port = port

    async def __call__(self, scope, receive, send):
        import ipaddress
        kind = scope.get('type')
        if kind not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        server = scope.get('server')
        listener = None
        try:
            if server and server[1] == self.port:
                address = ipaddress.ip_address(server[0])
                if address == ipaddress.ip_address('127.0.0.1'):
                    listener = 'loopback'
                elif address == ipaddress.ip_address(self.private_bind):
                    listener = 'private'
        except (ValueError, IndexError, TypeError):
            pass
        if listener == 'private':
            return await PrivateOriginBoundary(self.app, policy=self.private_policy)(scope, receive, send)
        if listener == 'loopback':
            headers = scope.get('headers', ())
            hosts = [v for k, v in headers if k.lower() == b'host']
            origins = [v for k, v in headers if k.lower() == b'origin']
            allowed = {f'127.0.0.1:{self.port}'.encode(), f'localhost:{self.port}'.encode()}
            host = hosts[0].lower() if len(hosts) == 1 else None
            expected_origin = b'http://' + host if host in allowed else None
            needs_origin = kind == 'websocket' or scope.get('method') not in ('GET', 'HEAD', 'OPTIONS')
            if (host in allowed and len(origins) <= 1 and (not origins or origins[0] == expected_origin)
                    and (not needs_origin or len(origins) == 1)
                    and scope.get('scheme') in ('http', 'ws')):
                scope.setdefault('state', {})['mira_voice_allowed'] = True
                return await self.app(scope, receive, send)
        if kind == 'websocket':
            await send({'type': 'websocket.close', 'code': 4403})
        else:
            await JSONResponse({'code':'private_origin_denied','message':'Use the origin for this listener.'},
                status_code=403, headers={'Cache-Control':'no-store'})(scope,receive,send)
