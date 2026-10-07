"""Allowlisted, loopback-only ASGI app for local memory management.

This factory intentionally does not load Settings or import the Actor,
providers, diagnostics, media, or application session router. Storage is opened
only from the existing operator-pair route after a valid one-use code.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from mira.application.memory_management import MemoryManagement
from mira.config.loader import ConfigurationError
from mira.entrypoints.http.memory_management_routes import router as memory_management_router
from mira.entrypoints.http.operator_pairing import OperatorPairing
from mira.entrypoints.http.operator_routes import COOKIE_NAME, router as operator_router

MANAGEMENT_FACTORY_TIMEOUT_SECONDS = 4.0
MANAGEMENT_CLOSE_TIMEOUT_SECONDS = 1.5
MAX_REQUEST_BYTES = 32_768
_ALLOWED_METHODS = {
    "/health": {"GET"},
    "/": {"GET"},
    "/local-memory.js": {"GET"},
    "/local-memory.css": {"GET"},
    "/api/v1/operator/status": {"GET"},
    "/api/v1/operator/pair": {"POST"},
    "/api/v1/operator/revoke": {"POST"},
    "/api/v1/memory-management/status": {"GET"},
    "/api/v1/memory-management/entries": {"GET"},
    "/api/v1/memory-management/operations": {"POST"},
}


def create_local_memory_app(*, management_factory: Callable[[], Awaitable[MemoryManagement]],
                           pairing: OperatorPairing, web_root: Path) -> FastAPI:
    """Compose only the management/pairing APIs and exact standalone resources."""
    if not callable(management_factory) or type(pairing) is not OperatorPairing:
        raise ConfigurationError("local_memory_runtime_configuration_invalid")
    if not isinstance(web_root, Path) or not web_root.is_absolute():
        raise ConfigurationError("local_memory_resource_root_invalid")
    if not pairing.expected_origins or any(
        origin not in {f"http://{authority}" for authority in ("127.0.0.1:8761", "localhost:8761")}
        and not origin.startswith("http://127.0.0.1:")
        and not origin.startswith("http://localhost:")
        for origin in pairing.expected_origins
    ):
        raise ConfigurationError("local_memory_origin_invalid")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime_lock = asyncio.Lock()
        manager: MemoryManagement | None = None
        factory_tasks: set[asyncio.Task] = set()
        late_close_tasks: set[asyncio.Task] = set()

        def close_late_manager(task: asyncio.Task) -> None:
            factory_tasks.discard(task)
            if task.cancelled():
                return
            try:
                late_manager = task.result()
            except BaseException:
                return
            if type(late_manager) is not MemoryManagement:
                return

            async def bounded_close() -> None:
                try:
                    await asyncio.wait_for(late_manager.aclose(), MANAGEMENT_CLOSE_TIMEOUT_SECONDS)
                except BaseException:
                    pass

            cleanup = asyncio.create_task(bounded_close())
            late_close_tasks.add(cleanup)
            cleanup.add_done_callback(late_close_tasks.discard)

        async def ensure_runtime() -> None:
            nonlocal manager
            if manager is not None and manager.is_open:
                return
            async with runtime_lock:
                if manager is not None and manager.is_open:
                    return
                task = asyncio.create_task(management_factory())
                try:
                    done, _pending = await asyncio.wait({task}, timeout=MANAGEMENT_FACTORY_TIMEOUT_SECONDS)
                    if not done:
                        factory_tasks.add(task)
                        task.add_done_callback(close_late_manager)
                        task.cancel()
                        raise TimeoutError("local_memory_factory_timeout") from None
                    value = task.result()
                    if type(value) is not MemoryManagement or not value.is_open:
                        if type(value) is MemoryManagement:
                            await asyncio.wait_for(value.aclose(), MANAGEMENT_CLOSE_TIMEOUT_SECONDS)
                        raise ConfigurationError("local_memory_manager_invalid")
                    manager = value
                    app.state.memory_management = manager
                except BaseException:
                    if not task.done() and task not in factory_tasks:
                        factory_tasks.add(task)
                        task.add_done_callback(close_late_manager)
                        task.cancel()
                    if manager is not None:
                        try:
                            await asyncio.wait_for(manager.aclose(), MANAGEMENT_CLOSE_TIMEOUT_SECONDS)
                        except BaseException:
                            pass
                        manager = None
                        app.state.memory_management = None
                    raise

        async def close_runtime() -> None:
            nonlocal manager
            async with runtime_lock:
                if manager is not None:
                    closing = manager
                    manager = None
                    app.state.memory_management = None
                    try:
                        await asyncio.wait_for(closing.aclose(), MANAGEMENT_CLOSE_TIMEOUT_SECONDS)
                    except BaseException:
                        pass
                for task in tuple(factory_tasks):
                    task.cancel()
                if factory_tasks:
                    _done, pending = await asyncio.wait(
                        tuple(factory_tasks), timeout=MANAGEMENT_CLOSE_TIMEOUT_SECONDS)
                    for task in pending:
                        task.cancel()
                if late_close_tasks:
                    done, pending = await asyncio.wait(
                        tuple(late_close_tasks), timeout=MANAGEMENT_CLOSE_TIMEOUT_SECONDS)
                    for task in pending:
                        task.cancel()
                    late_close_tasks.difference_update(done)

        app.state.ensure_runtime = ensure_runtime
        app.state.close_runtime = close_runtime
        try:
            yield
        finally:
            pairing.revoke()
            await close_runtime()

    app = FastAPI(title="MIRA Local Memory Console", version="1.0", docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.operator_pairing = pairing
    app.state.operator_app_id = str(uuid4())
    app.state.memory_management_enabled = True
    app.state.memory_management = None
    try:
        pairing.bind_app(app.state.operator_app_id)
    except ValueError:
        raise ConfigurationError("local_memory_pairing_already_bound") from None

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_only_boundary(request: Request, call_next):
        request.state.request_id = str(uuid4())
        path = request.url.path
        method = request.method.upper()
        request_id = request.state.request_id
        supported = _ALLOWED_METHODS.get(path)
        if supported is None:
            response = JSONResponse({"code": "not_found", "message": "Not found.",
                                     "request_id": request_id}, status_code=404)
        elif method not in supported:
            response = JSONResponse({"code": "method_not_allowed", "message": "Method not allowed.",
                                     "request_id": request_id}, status_code=405,
                                    headers={"Allow": ", ".join(sorted(supported))})
        else:
            origin = request.headers.get("origin")
            host = request.headers.get("host")
            origin_ok = (origin is None or any(
                origin == expected and OperatorPairing.host_matches(expected, host or "")
                for expected in pairing.expected_origins))
            if not origin_ok:
                response = JSONResponse({"code": "origin_denied", "message": "This origin is not allowed.",
                                         "request_id": request_id}, status_code=403)
            elif path.startswith("/api/v1/memory-management/"):
                authenticated = pairing.is_authenticated(
                    request.cookies.get(COOKIE_NAME), origin, host,
                    app_id=request.app.state.operator_app_id, method=method,
                    sec_fetch_site=request.headers.get("sec-fetch-site"),
                    referer=request.headers.get("referer"))
                if not authenticated:
                    response = JSONResponse({"code": "operator_authorization_required",
                                             "message": "Pair with the local operator first.",
                                             "request_id": request_id}, status_code=401)
                else:
                    try:
                        await request.app.state.ensure_runtime()
                    except Exception:
                        response = JSONResponse({"code": "operator_runtime_unavailable",
                                                 "message": "The local service is unavailable.",
                                                 "request_id": request_id}, status_code=503)
                    else:
                        response = None
            elif path == "/api/v1/operator/revoke":
                authenticated = pairing.is_authenticated(
                    request.cookies.get(COOKIE_NAME), origin, host,
                    app_id=request.app.state.operator_app_id, method=method,
                    sec_fetch_site=request.headers.get("sec-fetch-site"),
                    referer=request.headers.get("referer"))
                if not authenticated:
                    response = JSONResponse({"code": "operator_authorization_required",
                                             "message": "Pair with the local operator first.",
                                             "request_id": request_id}, status_code=401)
                else:
                    response = None
            else:
                response = None

            if response is None and path in {
                "/api/v1/operator/pair", "/api/v1/operator/revoke",
                "/api/v1/memory-management/operations",
            }:
                try:
                    size = int(request.headers.get("content-length", "0"))
                except ValueError:
                    size = MAX_REQUEST_BYTES + 1
                if size < 0 or size > MAX_REQUEST_BYTES or request.headers.get("transfer-encoding"):
                    response = JSONResponse({"code": "body_limit", "message": "Request too large.",
                                             "request_id": request_id}, status_code=413)
            if response is None:
                response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, _error: RequestValidationError) -> JSONResponse:
        return JSONResponse({"code": "invalid_request", "message": "Request does not match the contract.",
                             "request_id": request.state.request_id}, status_code=422)

    @app.exception_handler(Exception)
    async def safe_internal_error(request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse({"code": "internal_error", "message": "The local operation failed.",
                             "request_id": getattr(request.state, "request_id", "unavailable")},
                            status_code=500)

    app.include_router(operator_router)
    app.include_router(memory_management_router)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, object]:
        return {"status": "ok", "mode": "local-memory-management", "provider_transmission": False}

    @app.get("/", include_in_schema=False)
    async def page() -> Response:
        path = web_root / "local-memory.html"
        return (FileResponse(path, media_type="text/html") if path.is_file()
                else Response(status_code=404))

    @app.get("/local-memory.js", include_in_schema=False)
    async def script() -> Response:
        path = web_root / "dist/local-memory/main.js"
        return (FileResponse(path, media_type="text/javascript") if path.is_file()
                else Response(status_code=404))

    @app.get("/local-memory.css", include_in_schema=False)
    async def stylesheet() -> Response:
        path = web_root / "public/local-memory.css"
        return (FileResponse(path, media_type="text/css") if path.is_file()
                else Response(status_code=404))

    from mira.entrypoints.http.body_limit import BoundedRequestBody
    # Added last so actual byte limits run before route parsing and private factories.
    app.add_middleware(BoundedRequestBody)
    return app
