# WP03 Google voice: provider facts checked 2026-10-03 UTC

This is a public-document review, not project access, billing, quota, entitlement, or live audio verification.

## Exact selection and API surface

The requested `gemini-3.8-flash-tts` is a Preview model released 2026-09-28. Its documented location
is `global`; the model has audio output, text input, and streaming support. It is exposed through
Gemini Enterprise Agent Platform, not the Cloud Text-to-Speech API. The model page documents
OAuth bearer access to `aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/models/gemini-3.8-flash-tts:generateContent`.
[Official model card](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash-tts)
[Cloud TTS exclusion notice](https://docs.cloud.google.com/text-to-speech/docs/gemini-tts)

The streaming method is `streamGenerateContent?alt=sse`. The new wire shape uses
`speechConfig.voiceConfig.voice`, optional `speechMetadata.style`, and verbatim `parts[].text`.
Streaming PCM is signed little-endian 16-bit mono at 24 kHz; unary defaults to WAV with a header.
Explicit `responseFormat: [{audio: {mimeType: AUDIO_L16}}]` selects raw PCM. Output sample rate
cannot be chosen; MP3/Opus are unsupported. Thirty prebuilt voices include Kore, Puck and Aoede.
Extended/designed/replicated voices also exist, but this first adapter deliberately accepts only
prebuilt names and never creates a voice. Chinese simplified/traditional input is supported and
language is detected automatically. The implementation does not pretend `tts_language_code`
selects a different audio locale. SDK examples require google-genai >=2.25.0; direct REST avoids
that dependency. [Official generation and format guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/text-to-speech/overview)
[Migration guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/text-to-speech/migration-guide)

The Gemini Developer API guide is a separate product surface. Its API-key examples are not
evidence that an AI Studio key can authenticate this exact Enterprise model and STT V2 together.
[Developer API speech guide](https://ai.google.dev/gemini-api/docs/speech-generation)

## Minimum secure setup

One existing Google Cloud principal/ADC credential source can authenticate both APIs with the
cloud-platform OAuth scope and the necessary permissions. This is a common identity, not proof
that a given account is authorized. No private key needs to be put in a chat or source archive.
Use an approved workload identity or secure ADC mechanism supplied to the composition root.
Ordinary Google/gcloud sign-in alone is not evidence that application ADC is configured.
[Google ADC documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/gcp-auth)
[STT streaming auth scope and permission](https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v2)

Non-secret fields: project ID; optional quota project ID (can equal the resource project);
STT location/model/language; selected prebuilt TTS voice; optional speaking style. Exact TTS
model, global location and aiplatform endpoint should stay fixed. The existing STT selection
`us / chirp_3 / cmn-Hans-CN` is documented for streaming and Chinese transcription; the adapter
requires actual runtime validation rather than inferring entitlement from these fields.
[Chirp 3 regions and language support](https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3)

The user/project administrator must verify billing and enable `speech.googleapis.com` plus
`aiplatform.googleapis.com`. Generic Cloud TTS (`texttospeech.googleapis.com`) is not required
for this chosen model. Runtime inference needs `speech.recognizers.recognize` and
`aiplatform.endpoints.predict`; standard roles are Cloud Speech Client (`roles/speech.client`)
and Agent Platform User (`roles/aiplatform.user`), with a narrower pre-existing custom role
possible. API enablement is a separate administrative permission, not needed by a runtime user.
[Enterprise project setup](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start)
[Enterprise operation permissions](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/access-control)
[Speech roles](https://docs.cloud.google.com/iam/docs/roles-permissions/speech)

Quota-project billing may require `serviceusage.services.use`. TTS is Preview, so disclose the
[Google Cloud service-specific Preview terms](https://cloud.google.com/terms/service-terms)
and do not assume user acceptance. Global-only TTS cannot promise a selected regional residency.
No project creation, API enabling, IAM changes, credential grants, or live request was performed.
[Quota project permissions](https://docs.cloud.google.com/docs/quotas/set-quota-project)

## STT streaming details and source discrepancy

STT V2 bidirectional streaming is gRPC-only, not REST. A recognizer `_` can take a complete
configuration in the first request; following messages contain audio only. The backend provides
explicit LINEAR16/mono/rate configuration because AudioPacket contains raw PCM, not a WAV header.
Final STT segments mean recognition is final for that audio portion, not semantic turn completion.
[Streaming guide](https://docs.cloud.google.com/speech-to-text/docs/streaming-recognize)
[RPC reference](https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v2)

The guide and quota page say 25 KB per message, while the current RPC `audio` field says 15 KB.
This implementation uses 12,000-byte chunks and rejects configured chunk sizes above 15,000,
meeting both documents without pretending they agree. Streams are capped below five minutes;
callers must pace microphone audio near real time. There is no hidden endless-stream restart.
[Limits](https://docs.cloud.google.com/speech-to-text/docs/quotas)

## Concrete runtime dependencies

- google-cloud-speech==2.40.0: current official SpeechAsyncClient version and PyPI release
- google-auth[requests]==2.59.1: current official auth package, used only by explicit composition
- httpx==0.28.1: already pinned in development; promote to runtime for authenticated SSE
- No google-cloud-texttospeech or google-genai needed for this REST path

The director owns installation and the full resolved lock. Package metadata is not install or
compatibility evidence. [Speech SDK](https://docs.cloud.google.com/python/docs/reference/speech/latest/google.cloud.speech_v2.services.speech.SpeechAsyncClient)
[Speech package](https://pypi.org/project/google-cloud-speech/)
[Auth package](https://pypi.org/project/google-auth/)
[HTTPX](https://pypi.org/project/httpx/)
