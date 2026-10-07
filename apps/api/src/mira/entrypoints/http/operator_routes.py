"""Local operator pairing control plane. It contains no private memory data."""
import json

from fastapi import APIRouter, HTTPException, Request, Response

from mira.application.story import StoryCheckpointUpgradeRequired

from mira.entrypoints.http.device_pairing import DevicePairing
from mira.entrypoints.http.schemas import OperatorPairRequest, OperatorPairStatus

router = APIRouter(prefix="/api/v1/operator", tags=["local operator"])
COOKIE_NAME = "mira_operator_session"


@router.get("/status", response_model=OperatorPairStatus)
async def operator_status(request: Request) -> OperatorPairStatus:
    pairing = request.app.state.operator_pairing
    state = pairing.status(request.cookies.get(COOKIE_NAME)) if type(pairing) is DevicePairing else pairing.status()
    state["paired"] = state["paired"] and pairing.is_authenticated(
        request.cookies.get(COOKIE_NAME), request.headers.get("origin"), request.headers.get("host"),
        app_id=request.app.state.operator_app_id, method=request.method,
        sec_fetch_site=request.headers.get("sec-fetch-site"),
        referer=request.headers.get("referer"))
    return OperatorPairStatus(**state)


@router.post("/pair", status_code=204)
async def pair_operator(body: OperatorPairRequest, request: Request, response: Response) -> Response:
    pairing = request.app.state.operator_pairing
    origin, host = request.headers.get("origin"), request.headers.get("host")
    if not origin or not host:
        raise HTTPException(status_code=403, detail="operator_pairing_denied")
    cookie = pairing.pair(body.code, origin, host, app_id=request.app.state.operator_app_id)
    if cookie is None:
        status = pairing.status()
        raise HTTPException(status_code=423 if status["revoked"] else 401,
                            detail="operator_pairing_denied") from None
    # Pairing is not reported successful until the memory reader and runtime
    # are ready. Startup failure consumes and revokes the one-use code.
    try:
        await request.app.state.ensure_runtime()
    except Exception as error:
        if type(pairing) is DevicePairing:
            identity = pairing.revoke_device(cookie)
            await request.app.state.device_sessions.close_owner(identity, request.app.state.container)
        else:
            pairing.revoke()
            await request.app.state.close_runtime()
        if isinstance(error, StoryCheckpointUpgradeRequired):
            return Response(content=json.dumps({
                "code": error.code, "message": error.guidance,
                "request_id": request.state.request_id}), status_code=409,
                media_type="application/json", headers={"Cache-Control": "no-store"})
        raise HTTPException(status_code=503, detail="operator_runtime_unavailable") from None
    response.status_code = 204
    response.set_cookie(COOKIE_NAME, cookie, httponly=True, secure=origin.startswith("https://"),
                        samesite="strict", path="/api/v1",
                        max_age=pairing.session_ttl_seconds)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/revoke", status_code=204)
async def revoke_operator(request: Request) -> Response:
    pairing = request.app.state.operator_pairing
    if not pairing.is_authenticated(request.cookies.get(COOKIE_NAME),
                                    request.headers.get("origin"), request.headers.get("host"),
                                    app_id=request.app.state.operator_app_id):
        raise HTTPException(status_code=401, detail="operator_authorization_required")
    if type(pairing) is DevicePairing:
        identity = pairing.revoke_device(request.cookies.get(COOKIE_NAME))
        await request.app.state.device_sessions.close_owner(identity, request.app.state.container)
    else:
        pairing.revoke()
        await request.app.state.close_runtime()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/api/v1")
    response.headers["Cache-Control"] = "no-store"
    return response
