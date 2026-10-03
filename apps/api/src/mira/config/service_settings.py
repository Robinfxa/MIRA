"""External-service preparation settings, not registrations of live product adapters.

No authentication discovery, network calls, credential file reads, or model guesses.
The application factory remains fail-closed until its real adapters are implemented.
"""
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator

from mira.config.base import FrozenSettings

Route = Literal["codex_native", "gateway", "openai_api"]


def optional_identifier(value):
    if value == "":
        return None
    if isinstance(value, str) and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", value):
        raise ValueError("Expected a bounded identifier, not instructions or credentials.")
    return value


def optional_secret(value):
    if value == "":
        return None
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    if isinstance(raw, str) and (not raw.strip() or any(ch.isspace() for ch in raw)):
        raise ValueError("Credential must be a single nonblank token.")
    return value


class RouteSettings(FrozenSettings):
    text: Route = "codex_native"
    image: Route = "codex_native"
    vision: Route = "codex_native"


class ModelSelections(FrozenSettings):
    text_model: str | None = None
    image_model: str | None = None
    vision_model: str | None = None
    _identifiers = field_validator("text_model", "image_model", "vision_model", mode="before")(optional_identifier)


class GatewaySettings(ModelSelections):
    # This is a local preparation convention, NOT a claim that a gateway is running.
    base_url: str = "http://127.0.0.1:8317/v1"
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    access_confirmed: bool = False
    _key = field_validator("api_key", mode="before")(optional_secret)

    @field_validator("base_url")
    @classmethod
    def local_gateway_only(cls, value: str) -> str:
        url = urlsplit(value)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}
                or url.username is not None or url.password is not None
                or url.query or url.fragment or url.path not in {"/v1", "/v1/"}
                or url.port is None or not 1024 <= url.port <= 65535
                or any(ch.isspace() for ch in value)):
            raise ValueError("Use a numeric loopback HTTP address with an explicit port and /v1.")
        return value.rstrip("/")


class OpenAISettings(ModelSelections):
    base_url: Literal["https://api.openai.com/v1"] = "https://api.openai.com/v1"
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    _key = field_validator("api_key", mode="before")(optional_secret)


class JevSettings(FrozenSettings):
    base_url: Literal["https://api.typesafe.ai/v1"] = "https://api.typesafe.ai/v1"
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    model: str | None = None
    _key = field_validator("api_key", mode="before")(optional_secret)
    _model = field_validator("model", mode="before")(optional_identifier)


class SpeechSettings(FrozenSettings):
    # ENV-03: STT V2 and exact Gemini 3.8 Flash TTS are separate Google APIs.
    # Keep the capability labels explicit so future adapters can be added without
    # treating one generic "speech provider" as authority for both directions.
    asr_provider: Literal["google_cloud"] = "google_cloud"
    tts_provider: Literal["google_cloud"] = "google_cloud"
    auth: Literal["google_adc"] = "google_adc"
    project_id: str | None = None
    quota_project_id: str | None = None
    stt_location: str = "us"
    stt_model: str = "chirp_3"
    stt_language_code: str = "cmn-Hans-CN"
    tts_language_code: str = "cmn-CN"
    # Exact voice must be chosen from actual available voices; no guessed entitlement.
    tts_voice: str | None = None
    tts_endpoint: Literal["aiplatform.googleapis.com"] = "aiplatform.googleapis.com"
    tts_model: Literal["gemini-3.8-flash-tts"] = "gemini-3.8-flash-tts"
    tts_location: Literal["global"] = "global"
    tts_style: str | None = Field(default=None, max_length=500)
    _optional = field_validator("project_id", "quota_project_id", "tts_voice", mode="before")(optional_identifier)

    @field_validator("tts_style", mode="before")
    @classmethod
    def optional_style(cls, value):
        return None if value == "" else value

    @field_validator("stt_location", "stt_model", "stt_language_code", "tts_language_code")
    @classmethod
    def simple_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
            raise ValueError("Invalid regional, locale or model name.")
        return value

    @property
    def stt_endpoint(self) -> str:
        return "speech.googleapis.com" if self.stt_location == "global" else f"{self.stt_location}-speech.googleapis.com"

    @property
    def recognizer(self) -> str | None:
        if self.project_id is None:
            return None
        return f"projects/{self.project_id}/locations/{self.stt_location}/recognizers/_"


class MetadataProbeSettings(FrozenSettings):
    allow_metadata: bool = False
    max_requests: int = Field(default=0, ge=0, le=3)
    timeout_seconds: float = Field(default=5, gt=0, le=15)


class ServiceSettings(FrozenSettings):
    routes: RouteSettings = Field(default_factory=RouteSettings)
    codex: ModelSelections = Field(default_factory=ModelSelections)
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    jev: JevSettings = Field(default_factory=JevSettings)
    speech: SpeechSettings = Field(default_factory=SpeechSettings)
    probe: MetadataProbeSettings = Field(default_factory=MetadataProbeSettings)
