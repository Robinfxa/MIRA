# Composition proposal, owned by director

The new adapters implement the existing media ports. They do not register themselves, read
configuration/environment/credential files, enable live mode, or replace FixtureReview.

## Exact constructor contract

```python
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechAsyncClient
from google.cloud.speech_v2.types import cloud_speech
import httpx

from mira.adapters.speech.google_stt_v2 import (
    SttOptions, GoogleSpeechV2Backend, GoogleSpeechV2GrpcTransport,
)
from mira.adapters.speech.google_gemini_tts import (
    GeminiTtsOptions, GoogleGeminiTtsBackend, GoogleGeminiTtsRestTransport,
)

# credentials and token_provider arrive from explicit approved bootstrap auth.
# token_provider: async () -> current non-expired OAuth access token.
# Both derive from the same authorized Cloud identity, cloud-platform scope,
# with its approved quota project. No key string belongs in public settings.
stt_options = SttOptions(
    project_id=speech.project_id,
    location=speech.stt_location,
    model=speech.stt_model,
    language_code=speech.stt_language_code,
)
stt_client = SpeechAsyncClient(
    credentials=credentials,
    client_options=ClientOptions(api_endpoint=stt_options.endpoint),
)
stt = GoogleSpeechV2Backend(stt_options, GoogleSpeechV2GrpcTransport(
    stt_client, request_factory=cloud_speech.StreamingRecognizeRequest,
))
http_client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
tts_options = GeminiTtsOptions(
    project_id=speech.project_id,
    voice=speech.tts_voice,
    model=speech.tts_model,
    location=speech.tts_location,
    style=speech.tts_style,
)
tts = GoogleGeminiTtsBackend(tts_options, GoogleGeminiTtsRestTransport(
    http_client, token_provider=token_provider,
    quota_project_id=speech.quota_project_id,
))
```

This is a composition recipe, not executed live. Scope/duration/spend approval must be checked
before client use. An already-authorized Google credentials object may be supplied to the SDK;
HTTP's token_provider must refresh through an approved credential source as needed. A stale
literal access token is unsuitable for the 24-hour mission. User secrets never pass into specs,
logs, test evidence, frontend or serialized settings. Do not turn SDK DEBUG logging on.

Lifecycle owner closes `await http_client.aclose()` and `await stt_client.transport.close()`.
Adapters close per-call streams but do not close shared clients. Every consumer that stops early
must `await stream.aclose()`; cancellation propagates. Local playback Stop and epoch invalidation
must happen first, independently of network cancel acknowledgment. No automatic retries.

## Proposed shared integration changes

1. SpeechSettings now needs exact fixed tts_model/location/endpoint and optional style (director
   reports these are added). Keep STT location independent. Legacy tts_language_code is not sent
   to Gemini; output language is determined by approved text. Keep voice explicitly chosen.
2. The composition root constructs these providers only after explicit live capability admission,
   authentication and bounded spend approval. Keep current mock/replay profiles and real-content
   review guard unchanged. Do not route by provider inside SessionActor.
3. Send upstream mono PCM16 at a fixed 8–48-kHz rate and contiguous first_sample values. STT's
   cumulative TranscriptRevision is not a final semantic turn. One stream uses one ID/rate;
   duration overflow is explicit input_limit, with no hidden recognizer restart.
4. Send only approved text to TTS. Consume 24-kHz mono PCM16 AudioPackets with contiguous sample
   offsets. Missing terminal STOP raises incomplete_stream even after partial audio. The consumer
   must retain already-presented history and mark failure/cancel accurately.
5. Check consumers with affected architecture/config/providers/actor/http lanes and separate
   playback tests. providers lane already owns the new contract tests by test_*.py glob.

## Bounded first real smoke, after root authorization

Choose one short non-private Chinese sentence and one prebuilt voice. Authorize a maximum number
of calls and explicit currency budget, including whether an STT echo of synthesized audio may be
sent to Google. Make one exact-model TTS call, save only permitted audio and sanitized metadata
(model/region/sample count/latency/status), and verify WAV wrapping only at a file boundary.
Stream the approved PCM to STT with real-time pacing, one config message, and at most 12,000 bytes
per audio frame. Check expected transcript and separately perform cancel-after-first-packet.

Record actual endpoint/model and failure code without credentials, complete headers, private
payloads, or copied raw provider errors. Distinguish request accepted, bytes received, speech
intelligibility, actual playback and device-stop tail. None is currently verified live.
