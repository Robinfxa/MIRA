"""Application factory; imports neither open sockets nor load configuration."""
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from time import monotonic
import asyncio

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from mira.application.diagnostic_errors import classify_failure, public_error_code
from mira.application.diagnostic_events import (
    CancellationReason, DiagnosticCode, DiagnosticEvent, DiagnosticOutcome, DiagnosticStage,
    diagnostic_context, emit_safely, request_correlation,
)
from mira.application.ports.diagnostics import Diagnostics
from mira.application.ports.media import SpeechRecognitionBackend, SpeechSynthesisBackend
from mira.bootstrap.container import build_container
from mira.bootstrap.providers import GoogleVoiceProviders, Providers
from mira.config.loader import ConfigurationError, load_settings, project_root
from mira.config.settings import Settings
from mira.domain.errors import DomainError
from mira.entrypoints.http.routes import router
from mira.entrypoints.http.media_routes import router as media_router
from mira.entrypoints.http.schemas import MEDIA_WIRE_MODELS


def create_app(settings: Settings | None = None, *, providers: Providers | None = None,
               web_root: Path | None = None,
               speech_synthesis: SpeechSynthesisBackend | None = None,
               speech_recognition: SpeechRecognitionBackend | None = None,
               media_shutdown: Callable[[], Awaitable[None]] | None = None,
               voice_factory: Callable[[], GoogleVoiceProviders] | None = None,
               diagnostics: Diagnostics | None = None) -> FastAPI:
    configured = settings if settings is not None else load_settings()
    if configured.providers.generation == "rehearsal" and any(value is not None for value in (
            providers, speech_synthesis, speech_recognition, media_shutdown, voice_factory)):
        raise ConfigurationError("Offline rehearsal cannot be combined with injected providers or media.")
    if voice_factory is not None and any(value is not None for value in (
            speech_synthesis, speech_recognition, media_shutdown)):
        raise ConfigurationError("Use voice_factory or explicit media injection, not both.")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # SDK async channels must be created on this running app loop.
        voice = voice_factory() if voice_factory is not None else None
        if voice_factory is not None and voice is None:
            raise ConfigurationError("The explicit voice factory returned no providers.")
        container = None
        try:
            container = build_container(configured, providers=providers,
                speech_synthesis=voice.speech_synthesis if voice else speech_synthesis,
                speech_recognition=voice.speech_recognition if voice else speech_recognition,
                media_shutdown=voice.close if voice else media_shutdown, diagnostics=diagnostics)
            app.state.container = container
            yield
        finally:
            if container is not None:
                await container.close()
            elif voice is not None:
                await voice.close()

    app = FastAPI(title="MIRA Foundation", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    app.add_middleware(CORSMiddleware, allow_origins=list(configured.http.allowed_origins),
                       allow_methods=["GET", "POST", "DELETE"],
                       allow_headers=["Content-Type", "X-Mira-Session-Token"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        request.state.request_id = str(uuid4())
        context_token = request_correlation.set(request.state.request_id)
        started = monotonic()
        response = None
        outcome, code, reason = DiagnosticOutcome.FAILED, None, None
        try:
            if ((origin := request.headers.get("origin"))
                    and origin not in configured.http.allowed_origins):
                response = JSONResponse({"code": "origin_denied", "message": "此来源不被允许。",
                    "request_id": request.state.request_id}, status_code=403)
            else:
                try:
                    size = int(request.headers.get("content-length", "0"))
                except ValueError:
                    size = 1_000_000
                if size < 0 or size > 32768 or request.headers.get("transfer-encoding"):
                    response = JSONResponse({"code": "body_limit", "message": "输入超出大小限制，请缩短后重试。",
                        "request_id": request.state.request_id}, status_code=413)
                else:
                    response = await call_next(request)
            outcome = DiagnosticOutcome.SUCCEEDED if response.status_code < 400 else DiagnosticOutcome.FAILED
            code = None if response.status_code < 400 else classify_failure(
                http_status=response.status_code).code
        except asyncio.CancelledError:
            outcome, code, reason = (DiagnosticOutcome.CANCELLED, DiagnosticCode.CANCELLED,
                                     CancellationReason.DISCONNECT)
            raise
        except Exception:
            # The exception string/body may carry credentials or dialogue. Never reflect it.
            code = DiagnosticCode.UNKNOWN
            response = JSONResponse({"code": "internal_error", "message": "服务未完成操作，请重试或导出脱敏诊断。",
                "request_id": request.state.request_id}, status_code=500)
        finally:
            container = getattr(request.app.state, "container", None)
            emit_safely(container.diagnostics if container else None, DiagnosticEvent(
                DiagnosticStage.HTTP, outcome,
                diagnostic_context(session_id=request.path_params.get("session_id"),
                                   effect_id=request.path_params.get("effect_id")),
                code=code, cancellation_reason=reason,
                duration_ms=(monotonic() - started) * 1000,
                http_status=response.status_code if response is not None else None))
            request_correlation.reset(context_token)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError) -> JSONResponse:
        status = 404 if error.code == "session_not_found" else (
            503 if error.code in {"speech_unavailable", "microphone_unavailable"} else
            429 if error.code in {"session_capacity", "busy"} else 409
        )
        safe = classify_failure(error)
        return JSONResponse({"code": public_error_code(error.code), "message": safe.message + safe.action,
                             "request_id": request.state.request_id}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError) -> JSONResponse:
        # No reflected raw input, credentials, or complete validation error bodies.
        return JSONResponse({"code": "invalid_request", "message": "Request does not match the contract.",
                             "request_id": request.state.request_id}, status_code=422)

    app.include_router(router)
    app.include_router(media_router)

    def public_openapi():
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            components = schema.setdefault("components", {}).setdefault("schemas", {})
            for model in MEDIA_WIRE_MODELS:
                shape = model.model_json_schema(ref_template="#/components/schemas/{model}")
                components.update(shape.pop("$defs", {}))
                components[model.__name__] = shape
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = public_openapi
    root = web_root if web_root is not None else project_root() / "apps/web"
    if (root / "index.html").is_file():
        # Serve only public files and compiled JS, never project root or .env.
        app.mount("/assets", StaticFiles(directory=root / "public"), name="assets")
        app.mount("/dist", StaticFiles(directory=root / "dist", check_dir=False), name="dist")
        from fastapi.responses import FileResponse

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(root / "index.html")
    return app
