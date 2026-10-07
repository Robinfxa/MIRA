"""Same-origin admission and retirement for explicit trusted-LAN mode only."""
from fastapi import APIRouter, HTTPException, Request, Response

from mira.entrypoints.http.operator_routes import COOKIE_NAME

router = APIRouter(prefix='/api/v1/devices', tags=['trusted private network'])


@router.post('/bootstrap', status_code=204)
async def bootstrap_device(request: Request) -> Response:
    access = request.app.state.operator_pairing
    origin, host = request.headers.get('origin'), request.headers.get('host')
    if not origin or not host or origin not in access.expected_origins:
        raise HTTPException(status_code=403, detail='device_origin_required')
    cookie = access.admit(request.cookies.get(COOKIE_NAME), origin, host,
                          app_id=request.app.state.operator_app_id)
    if cookie is None:
        raise HTTPException(status_code=429, detail='device_capacity')
    try:
        await request.app.state.ensure_runtime()
        await request.app.state.device_sessions.sweep(request.app.state.container, access)
        if not access.is_authenticated(cookie, origin, host, app_id=request.app.state.operator_app_id):
            raise PermissionError('device_access_expired')
    except Exception:
        identity = access.revoke_device(cookie)
        await request.app.state.device_sessions.close_owner(identity, request.app.state.container)
        raise HTTPException(status_code=503, detail='device_runtime_unavailable') from None
    response = Response(status_code=204, headers={'Cache-Control': 'no-store'})
    response.set_cookie(COOKIE_NAME, cookie, httponly=True, secure=origin.startswith('https://'),
                        samesite='strict', path='/api/v1', max_age=access.session_ttl_seconds)
    return response


@router.post('/revoke', status_code=204)
async def revoke_device(request: Request) -> Response:
    access = request.app.state.operator_pairing
    cookie = request.cookies.get(COOKIE_NAME)
    if not access.is_authenticated(cookie, request.headers.get('origin'), request.headers.get('host'),
                                   app_id=request.app.state.operator_app_id, method=request.method):
        raise HTTPException(status_code=401, detail='device_authorization_required')
    identity = access.revoke_device(cookie)
    await request.app.state.device_sessions.close_owner(identity, request.app.state.container)
    response = Response(status_code=204, headers={'Cache-Control': 'no-store'})
    response.delete_cookie(COOKIE_NAME, path='/api/v1')
    return response
