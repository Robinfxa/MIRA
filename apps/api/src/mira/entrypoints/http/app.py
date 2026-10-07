"""Application factory; imports neither open sockets nor load configuration."""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from time import monotonic
import asyncio
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.datastructures import Headers

from mira.application.diagnostic_errors import classify_failure, public_error_code
from mira.application.diagnostic_events import (
    CancellationReason, DiagnosticCode, DiagnosticEvent, DiagnosticOutcome, DiagnosticStage,
    diagnostic_context, emit_safely, request_correlation,
)
from mira.application.ports.diagnostics import Diagnostics
from mira.application.ports.media import SpeechRecognitionBackend, SpeechSynthesisBackend
from mira.application.ports.continuous_speech import ContinuousSpeechRecognitionBackend
from mira.application.continuous_listening import ListeningLimits
from mira.application.ports.request_budget import RequestBudget
from mira.bootstrap.container import build_container
from mira.bootstrap.character_assets import renderer_readiness
from mira.bootstrap.providers import GoogleVoiceProviders, Providers
from mira.config.loader import ConfigurationError, load_settings, project_root
from mira.config.settings import Settings
from mira.domain.errors import DomainError
from mira.entrypoints.http.routes import router
from mira.entrypoints.http.audio_review_routes import router as audio_review_router
from mira.entrypoints.http.media_routes import router as media_router
from mira.entrypoints.http.continuous_listening_routes import router as continuous_listening_router
from mira.entrypoints.http.schemas import MEDIA_WIRE_MODELS
from mira.entrypoints.http.operator_routes import router as operator_router
from mira.entrypoints.http.operator_routes import COOKIE_NAME
from mira.entrypoints.http.operator_pairing import OperatorPairing
from mira.entrypoints.http.device_pairing import DevicePairing
from mira.entrypoints.http.trusted_device_access import TrustedDeviceAccess
from mira.entrypoints.http.device_sessions import DeviceSessions
from mira.entrypoints.http.private_origin import PrivateOriginBoundary, DualListenerBoundary
from mira.config.http_access import validate_http_access

MEMORY_FACTORY_STARTUP_TIMEOUT_SECONDS = 5.0


class _OperatorWebSocketBoundary:
    """HTTP middleware skips WebSockets, so gate the private socket separately."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        owner = scope.get("app")
        pairing = getattr(getattr(owner, "state", None), "operator_pairing", None)
        if scope.get("type") == "websocket" and pairing is not None:
            headers = Headers(scope=scope)
            raw_cookie = headers.get("cookie", "")
            cookie = None
            for part in raw_cookie.split(";"):
                name, separator, value = part.strip().partition("=")
                if separator and name == COOKIE_NAME:
                    cookie = value
                    break
            if not pairing.is_authenticated(cookie, headers.get("origin"), headers.get("host"),
                                            app_id=getattr(getattr(owner, "state", None), "operator_app_id", None)):
                await send({"type": "websocket.close", "code": 4403})
                return
            devices = getattr(owner.state, "device_sessions", None)
            if devices is not None and not devices.allows_path(pairing.identity(cookie), scope.get("path", "")):
                await send({"type": "websocket.close", "code": 4403})
                return
            try:
                await owner.state.ensure_runtime()
            except Exception:
                await send({"type": "websocket.close", "code": 1011})
                return
            if devices is not None:
                # Admission is a live lease: revoke/expiry also closes a quiet open
                # socket, even when no subsequent HTTP request or audio frame arrives.
                closed = False
                def access_alive():
                    identity = pairing.identity(cookie)
                    return identity is not None and devices.allows_path(identity, scope.get("path", ""))
                async def guarded_receive():
                    if not access_alive():
                        return {"type": "websocket.disconnect", "code": 4403}
                    message = await receive()
                    if not access_alive():
                        return {"type": "websocket.disconnect", "code": 4403}
                    return message
                async def guarded_send(message):
                    nonlocal closed
                    if closed:
                        return
                    if not access_alive() and message.get("type") != "websocket.close":
                        closed = True
                        await send({"type": "websocket.close", "code": 4403})
                        return
                    if message.get("type") == "websocket.close":
                        closed = True
                    await send(message)
                async def watch():
                    nonlocal closed
                    while access_alive():
                        await asyncio.sleep(0.5)
                    if not closed:
                        closed = True
                        await send({"type": "websocket.close", "code": 4403})
                application = asyncio.create_task(self.app(scope, guarded_receive, guarded_send))
                guard = asyncio.create_task(watch())
                try:
                    done, _ = await asyncio.wait((application, guard), return_when=asyncio.FIRST_COMPLETED)
                    if application in done:
                        await application
                    return
                finally:
                    application.cancel(); guard.cancel()
                    await asyncio.gather(application, guard, return_exceptions=True)
        await self.app(scope, receive, send)

if TYPE_CHECKING:
    from mira.application.actor_memory import SessionMemoryBinding
    from mira.application.memory_management import MemoryManagement


def create_app(settings: Settings | None = None, *, providers: Providers | None = None,
               web_root: Path | None = None,
               speech_synthesis: SpeechSynthesisBackend | None = None,
               speech_recognition: SpeechRecognitionBackend | None = None,
               continuous_speech_recognition: ContinuousSpeechRecognitionBackend | None = None,
               listening_limits: ListeningLimits | None = None,
               stt_request_budget: RequestBudget | None = None,
               media_shutdown: Callable[[], Awaitable[None]] | None = None,
               voice_factory: Callable[[], GoogleVoiceProviders] | None = None,
               diagnostics: Diagnostics | None = None,
               memory_factory: Callable[[], Awaitable[SessionMemoryBinding]] | None = None,
               memory_management_factory: Callable[[], Awaitable[MemoryManagement]] | None = None,
               operator_pairing: OperatorPairing | DevicePairing | TrustedDeviceAccess | None = None,
               authorize_memory_to_speech_provider: bool = False,
               character_factory: Callable | None = None,
               character_binding_factory: Callable | None = None,
               conversation_runtime_factory: Callable | None = None,
               loopback_port: int | None = None,
               character_renderer: str = 'static-pixi',
               story_image_factory: Callable | None = None) -> FastAPI:
    configured = settings if settings is not None else load_settings()
    try:
        private_policy = validate_http_access(configured.http.host, configured.http.port,
            configured.http.allowed_origins, configured.http.private_network)
    except ValueError:
        raise ConfigurationError("private_http_configuration_invalid") from None
    if loopback_port is not None and (type(loopback_port) is not int or private_policy is None
            or private_policy.scheme != 'http' or loopback_port != configured.http.port
            or type(operator_pairing) is not TrustedDeviceAccess):
        raise ConfigurationError('dual_listener_requires_trusted_private_http')
    allowed_origins = tuple(configured.http.allowed_origins)
    if loopback_port is not None:
        allowed_origins += (f'http://127.0.0.1:{loopback_port}', f'http://localhost:{loopback_port}')
    if private_policy is not None:
        if configured.diagnostics.development_recording:
            raise ConfigurationError("private_device_raw_recording_unavailable")
        if type(operator_pairing) not in (DevicePairing, TrustedDeviceAccess):
            raise ConfigurationError("private_device_pairing_required")
        if any(value is not None for value in (memory_factory, memory_management_factory,
                character_binding_factory, conversation_runtime_factory)):
            raise ConfigurationError("private_device_mode_ephemeral_only")
        if configured.runtime.max_sessions != (operator_pairing.max_devices if type(operator_pairing) is TrustedDeviceAccess else 2):
            raise ConfigurationError("private_device_session_capacity")
    elif type(operator_pairing) in (DevicePairing, TrustedDeviceAccess):
        raise ConfigurationError("device_pairing_requires_private_mode")
    if character_renderer not in ('static-pixi','code-native-review'):
        raise ConfigurationError('character_renderer_invalid')
    if configured.providers.generation == "rehearsal" and any(value is not None for value in (
            providers, speech_synthesis, speech_recognition, continuous_speech_recognition,
            listening_limits, stt_request_budget, media_shutdown, voice_factory, memory_factory,
            memory_management_factory, character_factory, character_binding_factory, conversation_runtime_factory)):
        raise ConfigurationError("Offline rehearsal cannot be combined with injected providers or media.")
    if voice_factory is not None and any(value is not None for value in (
            speech_synthesis, speech_recognition, continuous_speech_recognition,
        stt_request_budget, media_shutdown)):
        raise ConfigurationError("Use voice_factory or explicit media injection, not both.")
    if memory_factory is not None and (
            not callable(memory_factory) or configured.runtime.max_sessions != 1):
        raise ConfigurationError("memory_recall_requires_single_operator")
    if memory_factory is not None and operator_pairing is None:
        raise ConfigurationError("memory_operator_pairing_required")
    if memory_management_factory is not None and (
            not callable(memory_management_factory) or memory_factory is None):
        raise ConfigurationError("memory_management_requires_recall_mode")
    if operator_pairing is not None:
        if private_policy is None and memory_factory is None and character_binding_factory is None and conversation_runtime_factory is None:
            raise ConfigurationError("operator_pairing_requires_memory_mode")
        if operator_pairing.expected_origins != frozenset(allowed_origins):
            raise ConfigurationError("memory_operator_origins_mismatch")
    if character_binding_factory is not None and (not callable(character_binding_factory)
            or character_factory is not None or operator_pairing is None
            or configured.runtime.max_sessions != 1):
        raise ConfigurationError('character_persistence_requires_paired_single_operator')
    if conversation_runtime_factory is not None and (not callable(conversation_runtime_factory)
            or operator_pairing is None or configured.runtime.max_sessions != 1):
        raise ConfigurationError('conversation_requires_paired_single_operator')
    if type(authorize_memory_to_speech_provider) is not bool:
        raise ConfigurationError("memory_speech_consent_invalid")
    if authorize_memory_to_speech_provider and memory_factory is None:
        raise ConfigurationError("memory_speech_consent_requires_memory")
    if memory_factory is not None and not authorize_memory_to_speech_provider and any(value is not None for value in (
            voice_factory, speech_synthesis, speech_recognition, continuous_speech_recognition,
            stt_request_budget, media_shutdown)):
        # Recalled details can reach the speech provider in approved generated
        # speech. Local recording or text-provider consent does not cover it.
        raise ConfigurationError("memory_recall_text_only")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # SDK async channels must be created on this running app loop.
        voice = None
        memory_binding = None
        memory_management = None
        character_binding = None
        conversation_runtime = None
        container = None
        runtime_lock = asyncio.Lock()
        late_memory_tasks: set[asyncio.Task] = set()
        late_management_tasks: set[asyncio.Task] = set()
        late_management_close_tasks: set[asyncio.Task] = set()

        def require_current_pairing() -> None:
            # An earlier middleware authentication is not a lease to reopen
            # private resources after revoke/expiry while a request was waiting.
            if type(operator_pairing) is TrustedDeviceAccess:
                if not operator_pairing.active_identities():
                    raise PermissionError("device_runtime_unauthorized")
            elif operator_pairing is not None:
                status=operator_pairing.status()
                if status['revoked'] or not status['paired']:
                    raise PermissionError('operator_runtime_revoked')

        def close_late_memory_binding(task: asyncio.Task) -> None:
            late_memory_tasks.discard(task)
            if task.cancelled():
                return
            try:
                binding = task.result()
            except BaseException:
                return
            from mira.application.actor_memory import SessionMemoryBinding
            if type(binding) is SessionMemoryBinding:
                async def close_reader() -> None:
                    try:
                        await binding.reader.aclose()
                    except Exception:
                        pass
                asyncio.create_task(close_reader())

        def close_late_management(task: asyncio.Task) -> None:
            late_management_tasks.discard(task)
            if task.cancelled():
                return
            try:
                manager = task.result()
            except BaseException:
                return
            from mira.application.memory_management import MemoryManagement
            if type(manager) is MemoryManagement:
                async def close_manager() -> None:
                    try:
                        await manager.aclose()
                    except Exception:
                        pass
                close_task = asyncio.create_task(close_manager())
                late_management_close_tasks.add(close_task)
                close_task.add_done_callback(late_management_close_tasks.discard)

        async def close_runtime() -> None:
            nonlocal container, memory_binding, memory_management, character_binding, conversation_runtime
            async with runtime_lock:
                close_failed = False
                if container is not None:
                    try:
                        await container.close()
                    except Exception:
                        close_failed = True
                    finally:
                        container = None
                if conversation_runtime is not None:
                    try: await conversation_runtime.aclose()
                    except Exception: close_failed=True
                    finally: conversation_runtime=None
                if memory_binding is not None:
                    from mira.application.actor_memory import SessionMemoryBinding
                    if type(memory_binding) is SessionMemoryBinding:
                        try:
                            await memory_binding.reader.aclose()
                        except Exception:
                            close_failed = True
                    memory_binding = None
                if character_binding is not None:
                    try:
                        await character_binding.aclose()
                    except Exception:
                        close_failed=True
                    finally:
                        character_binding=None
                if memory_management is not None:
                    try:
                        await memory_management.aclose()
                    except Exception:
                        close_failed = True
                    finally:
                        memory_management = None
                if memory_factory is not None or character_binding_factory is not None or conversation_runtime_factory is not None:
                    app.state.container = None
                if memory_management_factory is not None:
                    app.state.memory_management = None
                for task in tuple(late_memory_tasks):
                    task.cancel()
                for task in tuple(late_management_tasks):
                    task.cancel()
                if late_management_close_tasks:
                    done, pending = await asyncio.wait(
                        tuple(late_management_close_tasks), timeout=1.0
                    )
                    for task in pending:
                        task.cancel()
                    late_management_close_tasks.difference_update(done)
                if close_failed:
                    raise RuntimeError("operator_runtime_close_failed") from None

        async def ensure_runtime() -> None:
            nonlocal voice, memory_binding, memory_management, container, character_binding, conversation_runtime
            require_current_pairing()
            if container is not None:
                return
            async with runtime_lock:
                require_current_pairing()
                if container is not None:
                    return
                try:
                    if character_binding_factory is not None:
                        from mira.bootstrap.character_story import CharacterRuntimeBinding
                        async with asyncio.timeout(MEMORY_FACTORY_STARTUP_TIMEOUT_SECONDS):
                            character_binding=await character_binding_factory()
                        if type(character_binding) is not CharacterRuntimeBinding:
                            raise ConfigurationError('character_binding_invalid')
                        require_current_pairing()
                    if conversation_runtime_factory is not None:
                        from mira.application.conversation_management import ConversationRuntime
                        async with asyncio.timeout(MEMORY_FACTORY_STARTUP_TIMEOUT_SECONDS):
                            conversation_runtime=await conversation_runtime_factory()
                        if type(conversation_runtime) is not ConversationRuntime:
                            raise ConfigurationError('conversation_runtime_invalid')
                        require_current_pairing()
                        app.state.conversation_runtime=conversation_runtime
                    voice = voice_factory() if voice_factory is not None else None
                    if voice_factory is not None and voice is None:
                        raise ConfigurationError("The explicit voice factory returned no providers.")
                    if memory_factory is not None:
                        from mira.application.actor_memory import SessionMemoryBinding
                        factory_task = asyncio.create_task(memory_factory())
                        try:
                            done, _pending = await asyncio.wait(
                                {factory_task}, timeout=MEMORY_FACTORY_STARTUP_TIMEOUT_SECONDS)
                        except BaseException:
                            late_memory_tasks.add(factory_task)
                            factory_task.add_done_callback(close_late_memory_binding)
                            factory_task.cancel()
                            raise
                        if not done:
                            late_memory_tasks.add(factory_task)
                            factory_task.add_done_callback(close_late_memory_binding)
                            factory_task.cancel()
                            raise TimeoutError("memory_factory_startup_timeout") from None
                        memory_binding = factory_task.result()
                        if (type(memory_binding) is not SessionMemoryBinding
                                or memory_binding.close_reader_on_actor_close):
                            raise ConfigurationError("memory_reader_ownership_invalid")
                        require_current_pairing()
                    if memory_management_factory is not None:
                        from mira.application.memory_management import MemoryManagement
                        factory_task = asyncio.create_task(memory_management_factory())
                        try:
                            done, _pending = await asyncio.wait(
                                {factory_task}, timeout=MEMORY_FACTORY_STARTUP_TIMEOUT_SECONDS)
                        except BaseException:
                            late_management_tasks.add(factory_task)
                            factory_task.add_done_callback(close_late_management)
                            factory_task.cancel()
                            raise
                        if not done:
                            late_management_tasks.add(factory_task)
                            factory_task.add_done_callback(close_late_management)
                            factory_task.cancel()
                            raise TimeoutError("memory_management_factory_startup_timeout") from None
                        memory_management = factory_task.result()
                        if (type(memory_management) is not MemoryManagement
                                or not memory_management.is_open):
                            raise ConfigurationError("memory_management_ownership_invalid")
                        app.state.memory_management = memory_management
                    require_current_pairing()
                    container = build_container(configured, providers=providers,
                                                story_image_factory=story_image_factory,
                                                character_review=character_renderer == 'code-native-review',
                        visual_readiness=renderer_readiness(character_renderer, web_root=root),
                        speech_synthesis=voice.speech_synthesis if voice else speech_synthesis,
                        speech_recognition=voice.speech_recognition if voice else speech_recognition,
                        continuous_speech_recognition=voice.continuous_speech_recognition if voice else continuous_speech_recognition,
                        listening_limits=listening_limits,
                        stt_request_budget=voice.stt_request_budget if voice else stt_request_budget,
                        media_shutdown=voice.close if voice else media_shutdown,
                        diagnostics=diagnostics,
                        **({"conversation_factory":conversation_runtime.create} if conversation_runtime is not None else {}),
                        **({"character_factory":character_binding.create} if character_binding is not None else
                           {"character_factory":character_factory} if character_factory is not None else {}),
                        **({"memory_binding": memory_binding,
                            "authorize_memory_to_speech_provider": authorize_memory_to_speech_provider}
                           if memory_binding is not None else {}))
                    app.state.container = container
                except BaseException:
                    if conversation_runtime is not None:
                        await conversation_runtime.aclose()
                        conversation_runtime=None
                        app.state.conversation_runtime=None
                    if character_binding is not None:
                        await character_binding.aclose()
                        character_binding=None
                    # If the reader opened but container construction failed, close it
                    # before exposing an unauthenticated/unready app state.
                    if memory_binding is not None:
                        from mira.application.actor_memory import SessionMemoryBinding
                        if type(memory_binding) is SessionMemoryBinding:
                            await memory_binding.reader.aclose()
                        memory_binding = None
                    if memory_management is not None:
                        await memory_management.aclose()
                        memory_management = None
                        app.state.memory_management = None
                    if voice is not None:
                        await voice.close()
                        voice = None
                    raise
        async def expire_devices():
            while True:
                await asyncio.sleep(0.5)
                try:
                    await app.state.device_sessions.sweep(app.state.container, operator_pairing)
                except Exception:
                    # Authentication still fails closed; retry bounded cleanup.
                    continue

        expiry_task = None
        try:
            app.state.close_runtime = close_runtime
            app.state.ensure_runtime = ensure_runtime
            if operator_pairing is None:
                await ensure_runtime()
            elif app.state.device_sessions is not None:
                expiry_task = asyncio.create_task(expire_devices())
            yield
        finally:
            if expiry_task is not None:
                expiry_task.cancel()
                await asyncio.gather(expiry_task, return_exceptions=True)
            try:
                if operator_pairing is not None:
                    operator_pairing.revoke()
                await close_runtime()
            finally:
                if memory_factory is not None or character_binding_factory is not None or conversation_runtime_factory is not None:
                    app.state.container = None

    app = FastAPI(title="MIRA Foundation", version="0.1.0", lifespan=lifespan)
    app.state.container = None
    app.state.http_allowed_origins = frozenset(allowed_origins)
    app.state.operator_pairing = operator_pairing
    app.state.device_sessions = DeviceSessions() if private_policy is not None else None
    app.state.conversation_runtime = None
    app.state.memory_mode = memory_factory is not None
    app.state.character_renderer = character_renderer
    app.state.memory_management_enabled = memory_management_factory is not None
    app.state.memory_management = None
    app.state.operator_app_id = str(uuid4()) if operator_pairing is not None else None
    if operator_pairing is not None:
        try:
            operator_pairing.bind_app(app.state.operator_app_id)
        except ValueError:
            raise ConfigurationError("memory_operator_pairing_already_bound") from None
    if private_policy is None:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    if operator_pairing is not None:
        app.add_middleware(_OperatorWebSocketBoundary)
    app.add_middleware(CORSMiddleware, allow_origins=list(allowed_origins),
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
            origin = request.headers.get("origin")
            host = request.headers.get("host")
            pairing = getattr(request.app.state, "operator_pairing", None)
            operator_control = request.url.path in {
                "/api/v1/operator/status", "/api/v1/operator/pair", "/api/v1/operator/revoke"}
            if type(pairing) is TrustedDeviceAccess:
                operator_control = request.url.path in {"/api/v1/devices/bootstrap", "/api/v1/devices/revoke"}
            if pairing is not None and request.url.path.startswith("/api/v1/"):
                if request.method not in {"GET", "HEAD", "OPTIONS"} and not origin:
                    response = JSONResponse({"code": "origin_required", "message": "Origin header required.",
                        "request_id": request.state.request_id}, status_code=403)
                elif not operator_control:
                    if not pairing.is_authenticated(request.cookies.get(COOKIE_NAME), origin, host,
                                                    app_id=request.app.state.operator_app_id,
                                                    method=request.method,
                                                    sec_fetch_site=request.headers.get("sec-fetch-site"),
                                                    referer=request.headers.get("referer")):
                        response = JSONResponse({"code": "operator_authorization_required",
                            "message": ("请刷新页面重新连接此设备。" if type(pairing) is TrustedDeviceAccess
                                        else "Pair with the local operator first."),
                            "request_id": request.state.request_id}, status_code=401)
                    else:
                        try:
                            await request.app.state.ensure_runtime()
                            devices = request.app.state.device_sessions
                            if devices is not None:
                                await devices.sweep(request.app.state.container, pairing)
                                identity = pairing.identity(request.cookies.get(COOKIE_NAME))
                                request.state.device_identity = identity
                                if identity is None or not devices.allows_path(identity, request.url.path):
                                    response = JSONResponse({"code": "device_session_denied",
                                        "message": "This session belongs to a different device.",
                                        "request_id": request.state.request_id}, status_code=403)
                        except Exception as error:
                            from mira.application.story import StoryCheckpointUpgradeRequired
                            if isinstance(error, StoryCheckpointUpgradeRequired):
                                response = JSONResponse({"code": error.code,
                                    "message": error.guidance,
                                    "request_id": request.state.request_id}, status_code=409,
                                    headers={"Cache-Control": "no-store"})
                            else:
                                response = JSONResponse({"code": "operator_runtime_unavailable",
                                    "message": "The local service is unavailable.",
                                    "request_id": request.state.request_id}, status_code=503)
            if response is None and ((origin := request.headers.get("origin"))
                    and origin not in allowed_origins):
                response = JSONResponse({"code": "origin_denied", "message": "此来源不被允许。",
                    "request_id": request.state.request_id}, status_code=403)
            elif response is None:
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

    from mira.entrypoints.http.story_image_routes import router as story_image_router
    app.include_router(story_image_router)
    app.include_router(router)
    app.include_router(audio_review_router)
    app.include_router(media_router)
    app.include_router(continuous_listening_router)
    from mira.entrypoints.http.memory_management_routes import router as memory_management_router
    app.include_router(memory_management_router)
    from mira.entrypoints.http.conversation_routes import router as conversation_router
    app.include_router(conversation_router)
    if type(operator_pairing) is TrustedDeviceAccess:
        from mira.entrypoints.http.trusted_device_routes import router as trusted_device_router
        app.include_router(trusted_device_router)
    elif operator_pairing is not None:
        app.include_router(operator_router)

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
        async def index(request: Request):
            if (operator_pairing is None and memory_management_factory is None and character_renderer=='static-pixi'
                    and getattr(app.state,'memory_recipients_label',None) is None):
                return FileResponse(root / "index.html")
            html = (root / "index.html").read_text(encoding="utf-8")
            body_start = html.lower().find("<body")
            if body_start < 0:
                raise RuntimeError("memory_operator_page_missing_body") from None
            tag_end = html.find(">", body_start)
            if tag_end < 0:
                raise RuntimeError("memory_operator_page_invalid") from None
            attributes = []
            if not getattr(request.state, "mira_voice_allowed", True):
                attributes.append(' data-private-http-text="true"')
            if character_renderer=='code-native-review':
                attributes.append(' data-character-renderer="code-native-review"')
            if operator_pairing is not None and type(operator_pairing) is not TrustedDeviceAccess:
                attributes.append(' data-operator-pairing="required"')
            if type(operator_pairing) is TrustedDeviceAccess:
                attributes.append(' data-device-access="trusted-private-network-no-pairing"')
                attributes.append(f' data-device-capacity="{operator_pairing.max_devices}"')
            elif private_policy is not None:
                attributes.append(' data-device-access="private"')
                html = html.replace('连接本机记忆模式', '连接此设备', 1)
                html = html.replace('此配对只确认本机操作员；', '手机和电脑分别使用一个配对码。此配对只授权本次服务中的独立临时会话；', 1)
            if conversation_runtime_factory is not None:
                attributes.append(' data-conversation-archive="enabled"')
            if memory_management_factory is not None:
                attributes.append(' data-memory-management="enabled"')
            html = html[:tag_end] + "".join(attributes) + html[tag_end:]
            if conversation_runtime_factory is not None:
                html=html.replace('连接本机记忆模式</h2>',
                    '连接本机会话记录模式</h2><p>本次启动已单独启用本机会话记录：配对后可保存已接受输入与实际软件回执。历史召回仍须选择具体来源并单独同意接收方。</p>')
                html=html.replace('对话只保留在当前页面，刷新后清空。',
                    '已单独启用本机会话记录；保存结果请查看“本机会话记录”面板。刷新不撤销已保存内容。')
            recipients = getattr(app.state, "memory_recipients_label", None)
            if recipients is not None:
                from html import escape
                # The factory supplies a fixed public service label. This read-only
                # disclosure happens on the pairing page before private runtime opens.
                safe_label = escape(recipients, quote=True)
                old = "Codex 生成与 TypeSafe/JEV 输出审核"
                if old in html:
                    html = html.replace(old, safe_label)
                else:
                    # Custom local markup must still name the selected recipients.
                    html = html[:tag_end] + html[tag_end:].replace(">", ">" +
                        '<p data-memory-recipient-disclosure>已单独授权的记忆接收方：' +
                        safe_label + '。自动记录仍关闭。</p>', 1)
            return HTMLResponse(html)
    from mira.entrypoints.http.body_limit import BoundedRequestBody
    # Added last so actual byte limits run before route parsing and private factories.
    app.add_middleware(BoundedRequestBody)
    if private_policy is not None:
        # Outer boundary runs before pairing, CORS, resource setup or socket accept.
        if loopback_port is not None:
            app.add_middleware(DualListenerBoundary, private_policy=private_policy,
                private_bind=configured.http.host, port=loopback_port)
        else:
            app.add_middleware(PrivateOriginBoundary, policy=private_policy)
    return app
