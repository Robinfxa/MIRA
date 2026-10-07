"""Run MIRA's separately admitted, bounded Google voice development app."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
_GOOGLE_CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_VOICE_REQUESTS_MAX = 100
_VOICE_SECONDS_MAX = 290.0
_PROXY_KEYS = frozenset(("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                         "http_proxy", "https_proxy", "all_proxy"))
_NETWORK_KEYS = _PROXY_KEYS | frozenset((
    "NO_PROXY", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
))


class EntryError(ValueError):
    """Safe user-facing diagnostic; never includes file contents or credentials."""


def _ensure_project_importable() -> None:
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _read_text_admission(path: Path):
    _ensure_project_importable()
    from tools.live_dev import EntryError as TextEntryError, _read_admission

    try:
        return _read_admission(path)
    except TextEntryError as error:
        raise EntryError(str(error)) from None


def _load_explicit_settings(path: Path, *, port: int):
    _ensure_project_importable()
    from tools.live_dev import EntryError as TextEntryError, _load_settings

    try:
        return _load_settings(path, port=port)
    except TextEntryError as error:
        raise EntryError(str(error)) from None


def _check_text_settings(settings, admission) -> None:
    _ensure_project_importable()
    from tools.live_dev import EntryError as TextEntryError, _check_settings

    # A voice-only session still uses the existing Codex/JEV route for dialogue.
    try:
        _check_settings(settings, admission, require_jev=True)
    except TextEntryError as error:
        raise EntryError(str(error)) from None


def _prepare_frontend() -> None:
    _ensure_project_importable()
    from tools.live_dev import _prepare_frontend as prepare

    prepare()


def _voice_request_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be an integer from 1 to {_VOICE_REQUESTS_MAX}; selected profile may impose a lower limit") from None
    if str(count) != value or not 1 <= count <= _VOICE_REQUESTS_MAX:
        raise argparse.ArgumentTypeError(f"must be an integer from 1 to {_VOICE_REQUESTS_MAX}; selected profile may impose a lower limit")
    return count


def _voice_duration(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be finite and in (0, 290] seconds") from None
    if not math.isfinite(seconds) or not 0 < seconds <= _VOICE_SECONDS_MAX:
        raise argparse.ArgumentTypeError("must be finite and in (0, 290] seconds")
    return seconds


def _build_parser() -> argparse.ArgumentParser:
    disclosure = (
        "Voice is opt-in and separate from Codex/JEV text admission. After browser permission and "
        "an explicit user gesture, microphone audio is sent to Google Speech-to-Text V2; "
        "approved text "
        "is sent to Google Gemini 3.8 Flash TTS; prior app dialogue is sent to Codex/JEV under the "
        "existing text admission. This may incur provider charges. Request counters apply to one "
        "running app instance and reset on restart; TTS/STT duration ceilings apply per stream. "
        "These finite technical ceilings are not dollar caps. "
        "A successful check is setup-declared only; it does not verify credentials, entitlement, "
        "quota, live readiness, or a dollar limit. Server startup never opens the browser "
        "microphone."
    )
    parser = argparse.ArgumentParser(description=disclosure, epilog=disclosure)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "serve"):
        command = subcommands.add_parser(name, description=disclosure)
        command.add_argument("--env-file", type=Path, required=True,
                             help="explicit private MIRA .env outside this checkout")
        command.add_argument("--admission", type=Path, required=True,
                             help="private explicit Codex/JEV admission JSON outside this checkout")
        command.add_argument("--usage-profile", choices=("probe", "application"), default="probe",
                             help="voice usage profile; must match the admission profile (application must be explicit)")
        command.add_argument(
            "--adc-file", type=Path, required=True,
            help="existing private absolute Google ADC file; check reads path metadata only",
        )
        command.add_argument("--authorize-google-voice-data-and-spend", action="store_true",
                             required=True,
                             help=("required separate voice/data/spend acknowledgement: microphone "
                                   "audio to Google STT, approved text to Google Gemini TTS, and "
                                   "provider charges; request/duration bounds are not dollar caps"))
        command.add_argument(
            "--tts-requests", type=_voice_request_count, required=True,
            help="required irreversible TTS dispatch ceiling per app instance (1–100; profile-bounded)",
        )
        command.add_argument(
            "--stt-requests", type=_voice_request_count, required=True,
            help="required irreversible STT dispatch ceiling per app instance (1–100; profile-bounded)",
        )
        command.add_argument(
            "--tts-max-seconds", type=_voice_duration, required=True,
            help="required TTS output stream duration ceiling (0–30 seconds)",
        )
        command.add_argument(
            "--stt-max-seconds", type=_voice_duration, required=True,
            help="required STT input stream duration ceiling (0–30 for probe; ≤290 for application)",
        )
        command.add_argument("--port", type=int, default=8000)
    return parser


def _private_adc_file(path: Path) -> Path:
    _ensure_project_importable()
    from tools.live_dev import EntryError as TextEntryError, _private_external_file

    try:
        return _private_external_file(path, label="Google ADC file")
    except TextEntryError:
        raise EntryError(
            "Google ADC file must be a private owner-only regular file outside the repository."
        ) from None


def _voice_limits(args, usage_profile: str | None = None):
    _ensure_project_importable()
    from mira.bootstrap.development_voice import DevelopmentVoiceLimits
    from mira.config.loader import ConfigurationError

    try:
        return DevelopmentVoiceLimits(
            tts_request_limit=args.tts_requests,
            stt_request_limit=args.stt_requests,
            tts_max_audio_seconds=args.tts_max_seconds,
            stt_max_input_seconds=args.stt_max_seconds,
            usage_profile=usage_profile or args.usage_profile,
        )
    except ConfigurationError:
        raise EntryError("Voice request and duration limits are invalid.") from None


def _validate_voice_settings(settings):
    _ensure_project_importable()
    from mira.config.service_settings import SpeechSettings

    speech = settings.services.speech
    if (type(speech) is not SpeechSettings or speech.auth != "google_adc"
            or speech.asr_provider != "google_cloud" or speech.tts_provider != "google_cloud"
            or not speech.project_id or speech.stt_model != "chirp_3"
            or speech.tts_model != "gemini-3.8-flash-tts" or speech.tts_voice != "Kore"
            or speech.tts_location != "global"):
        raise EntryError("The explicit env file must use Google Speech-to-Text V2 chirp_3 and "
                         "Gemini 3.8 Flash TTS, Kore, global, with a project ID.")
    return speech


def _safe_proxy(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (parsed.scheme.lower() in ("http", "https")
                and bool(parsed.hostname) and parsed.username is None and parsed.password is None
                and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def _ensure_approved_network_environment(runtime) -> None:
    approved = {key: value for key, value in runtime.environment.items() if key in _NETWORK_KEYS}
    current = {key: value for key, value in os.environ.items() if key in _NETWORK_KEYS}
    if current != approved:
        raise EntryError(
            "Current proxy or certificate environment differs from the approved runtime; "
            "voice serving did not start."
        )
    if (any(not _safe_proxy(value) for key, value in approved.items()
            if key in _PROXY_KEYS and value)
            or any("@" in approved.get(key, "") for key in ("NO_PROXY", "no_proxy"))):
        raise EntryError("Approved proxy settings contain an unsupported route or user-info value.")


def _load_google_credentials(path: Path):
    """Load only the caller-selected ADC through Google's supported auth SDK."""
    try:
        import google.auth

        credentials, _project = google.auth.load_credentials_from_file(
            str(path), scopes=(_GOOGLE_CLOUD_SCOPE,),
        )
    except Exception:
        raise EntryError("Google credentials could not be loaded from the explicit ADC file; "
                         "credential details were suppressed.") from None
    if credentials is None:
        raise EntryError("Google auth SDK returned no credentials for the explicit ADC file.")
    return credentials


def _make_google_token_provider(credentials):
    """Adapt the official credential object to the existing async TTS token port."""
    if (not callable(getattr(credentials, "refresh", None))
            or not hasattr(credentials, "valid") or not hasattr(credentials, "token")):
        raise EntryError("Google auth SDK returned an unsupported credentials object.")
    lock = asyncio.Lock()

    async def token_provider() -> str:
        try:
            async with lock:
                if not credentials.valid:
                    from google.auth.transport.requests import Request

                    await asyncio.to_thread(credentials.refresh, Request())
                token = credentials.token
        except Exception:
            raise RuntimeError("google_auth_refresh_failed") from None
        if not isinstance(token, str) or not token:
            raise RuntimeError("google_auth_token_unavailable")
        return token

    return token_provider


def _new_google_http_client(runtime):
    """Use only the proxy and CA environment pinned and rechecked for this runtime."""
    _ensure_approved_network_environment(runtime)
    try:
        import httpx

        return httpx.AsyncClient(trust_env=True, follow_redirects=False)
    except Exception:
        raise EntryError("Google TTS transport could not be prepared safely.") from None


def _make_google_stt_tls(runtime):
    """Bridge an explicitly approved CA file to standard verifying gRPC TLS."""
    _ensure_approved_network_environment(runtime)
    environment = runtime.environment
    selected = environment.get("SSL_CERT_FILE") or environment.get("REQUESTS_CA_BUNDLE")
    if not selected:
        if environment.get("SSL_CERT_DIR"):
            raise EntryError("Google STT requires an explicit approved CA file when custom "
                             "directory roots are configured.")
        return None  # Ordinary installations retain the vendor's platform roots.
    try:
        import grpc
        import ssl

        path = Path(selected)
        if not path.is_absolute() or not path.is_file():
            raise ValueError("invalid_ca_path")
        with path.open("rb") as source:
            roots = source.read(8 * 1024 * 1024 + 1)
        if not roots or len(roots) > 8 * 1024 * 1024 or b"PRIVATE KEY" in roots:
            raise ValueError("invalid_ca_bundle")
        ssl.create_default_context(cadata=roots.decode("ascii"))
        return grpc.ssl_channel_credentials(root_certificates=roots)
    except Exception:
        raise EntryError("Google STT approved CA file could not be validated; "
                         "no fallback trust settings were used.") from None


def _own_tts_http_client(factory, http_client):
    _ensure_project_importable()
    from mira.bootstrap.providers import GoogleVoiceProviders

    def voice_factory():
        try:
            bundle = factory()
        except Exception:
            raise EntryError(
                "Google voice startup failed; credentials and provider details were suppressed."
            ) from None

        async def shutdown() -> None:
            try:
                await bundle.close()
            finally:
                await http_client.aclose()

        return GoogleVoiceProviders(bundle.speech_recognition, bundle.speech_synthesis, shutdown)

    return voice_factory


def _close_http_client(http_client) -> None:
    if http_client is None or getattr(http_client, "is_closed", False):
        return
    try:
        # The CLI owns this temporary loop, not a stopped loop installed by an
        # embedding caller. An explicit loop factory avoids clearing its policy.
        with asyncio.Runner(loop_factory=asyncio.new_event_loop) as runner:
            runner.run(http_client.aclose())
    except Exception:
        # Lifespan normally owns the client; this is a final startup-failure cleanup.
        pass


def _run_uvicorn(app, *, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, workers=1, access_log=False,
                ws_max_size=32768, ws_max_queue=8)


def _status(settings, admission, voice_limits) -> dict:
    speech = settings.services.speech
    return {
        "armed": False,
        "declaration_checked": True,
        "admission_authorized": admission.authorized,
        "route_kind": admission.route_kind,
        "usage_profile": admission.usage_profile,
        "voice_mode": "declared_only",
        "voice_data_spend_acknowledged": True,
        "speech_selection": {
            "stt_provider": speech.asr_provider,
            "stt_model": speech.stt_model,
            "stt_location": speech.stt_location,
            "stt_language": speech.stt_language_code,
            "tts_provider": speech.tts_provider,
            "tts_model": speech.tts_model,
            "tts_voice": speech.tts_voice,
            "tts_location": speech.tts_location,
        },
        "adc_file": "explicit_private_path_declared",
        "auth_contents": "not_read",
        "credentials_loaded": False,
        "provider_activity": "not_run",
        "network_activity": "not_run",
        "inference": "not_run",
        "live_ready": False,
        "quota_or_entitlement_verified": False,
        "spend_dollar_cap": None,
        "limits_are_dollar_caps": False,
        "request_limits_scope": "per_app_invocation_in_memory; restart_starts_a_fresh_allowance",
        "duration_limits_scope": "per_tts_audio_stream_and_per_stt_input_stream",
        "limits": {
            "codex_requests_per_instance": admission.limits.codex_requests,
            "input_jev_requests_per_instance": admission.limits.input_jev_requests,
            "output_jev_requests_per_instance": admission.limits.output_jev_requests,
            "tts_requests_per_instance": voice_limits.tts_request_limit,
            "stt_requests_per_instance": voice_limits.stt_request_limit,
            "tts_max_audio_seconds_per_stream": voice_limits.tts_max_audio_seconds,
            "stt_max_stream_seconds_per_stream": voice_limits.stt_max_input_seconds,
        },
        "data_scope": {
            "microphone_audio": "Google Speech-to-Text V2",
            "approved_speech_text": "Google Gemini Enterprise TTS",
            "prior_app_dialogue": "Codex and JEV under text admission",
        },
        "microphone_capture_on_startup": False,
        "microphone_requires_browser_user_gesture": True,
    }


def _app_settings_for_port(settings, port: int):
    return settings.model_copy(update={
        "http": settings.http.model_copy(update={
            "host": "127.0.0.1", "port": port,
            "allowed_origins": (f"http://127.0.0.1:{port}", f"http://localhost:{port}"),
        }),
    })


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list:
        print("Unarmed: no configuration, admission, ADC contents, or provider activity "
              "was accessed.")
        return 0
    _ensure_project_importable()
    parser = _build_parser()
    args = parser.parse_args(args_list)
    http_client = None
    try:
        if type(args.port) is not int or not 1024 <= args.port <= 65535:
            raise EntryError("Port must be between 1024 and 65535.")
        # Validate the explicit profile and all request/duration limits before opening
        # admission, config, ADC metadata or any provider-related resource.
        voice_limits = _voice_limits(args, args.usage_profile)
        admission = _read_text_admission(args.admission)
        if admission.usage_profile != args.usage_profile:
            raise EntryError("Voice usage profile must exactly match the text admission profile.")
        settings = _load_explicit_settings(args.env_file, port=args.port)
        _check_text_settings(settings, admission)
        speech_settings = _validate_voice_settings(settings)
        adc_file = _private_adc_file(args.adc_file)

        if args.command == "check":
            print(json.dumps(_status(settings, admission, voice_limits), sort_keys=True))
            return 0

        _ensure_approved_network_environment(admission.runtime)
        stt_tls = _make_google_stt_tls(admission.runtime)
        _prepare_frontend()
        credentials = _load_google_credentials(adc_file)
        token_provider = _make_google_token_provider(credentials)
        http_client = _new_google_http_client(admission.runtime)

        from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
        from mira.bootstrap.development_app import (
            create_development_app, jev_transport_from_settings,
        )
        from mira.bootstrap.development_voice import create_development_voice_factory

        voice_factory = create_development_voice_factory(
            speech_settings=speech_settings, credentials=credentials,
            token_provider=token_provider, authorized=True, limits=voice_limits,
            http_client=http_client, stt_ssl_channel_credentials=stt_tls,
        )
        voice_factory = _own_tts_http_client(voice_factory, http_client)
        transport = jev_transport_from_settings(settings)
        app = create_development_app(
            runtime=admission.runtime, settings=_app_settings_for_port(settings, args.port),
            route_kind=admission.route_kind, input_transport=transport, output_transport=transport,
            authorized=admission.authorized, decision_policy=USER_DEVELOPMENT_0_6_V2,
            codex_request_limit=admission.limits.codex_requests,
            session_turn_limit=admission.limits.session_turns,
            input_request_limit=admission.limits.input_jev_requests,
            output_request_limit=admission.limits.output_jev_requests,
            input_timeout_seconds=admission.limits.input_jev_timeout_seconds,
            output_timeout_seconds=admission.limits.output_jev_timeout_seconds,
            usage_profile=admission.usage_profile,
            voice_factory=voice_factory, voice_usage_limits=voice_limits,
            voice_required=True,
        )
        print("Starting explicitly admitted MIRA development voice app on http://127.0.0.1:"
              + str(args.port) + "; microphone audio goes to Google STT after browser permission "
              "and user gesture, approved text goes to Google Gemini TTS, and prior app dialogue "
              "goes to Codex/JEV under text admission. Per-instance request/duration ceilings are "
              "not dollar caps; setup does not verify live entitlement or quota.", flush=True)
        _run_uvicorn(app, port=args.port)
        return 0
    except EntryError as error:
        print(f"Entry error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("Entry error: voice startup failed; credential and provider details were suppressed.",
              file=sys.stderr)
        return 2
    finally:
        _close_http_client(http_client)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "apps/api/src"))
    raise SystemExit(main())
