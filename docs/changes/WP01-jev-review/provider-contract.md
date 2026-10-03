# TypeSafe primary contract check · 2026-10-03 09:09–09:11 UTC

Public documentation was read. No authenticated catalogue or inference request was made.
These facts describe the service contract, not this user's account readiness.

## Minimal secure setup

- Secret: TypeSafe's own API key, supplied only through the parent's secure entry flow
  and injected as SecretStr. Existing loader alias: TYPESAFE_API_KEY.
- Model: jev-1.13.0, the currently documented fixed version. Do not freeze jev-latest
  or jev-preview, which move. Existing loader field: services.jev.model.
- Origin: https://api.typesafe.ai/v1, fixed by current settings. No region/project field.
- Authentication: Bearer header. The user gets their key from the official
  [console](https://console.typesafe.ai/). No key generation, credentials entry,
  account acceptance, enabled billing or live call was performed here.

[Quickstart](https://docs.typesafe.ai/introduction/quickstart) and
[OpenAPI](https://api.typesafe.ai/openapi.json) verified the route and authentication.

## Wire and primitives

POST /v1/systemone takes state (text/object/array), model and a questions map.
Response: model, answers keyed exactly as requested, and usage.input_tokens /
usage.output_tokens. Question IDs are correlation keys, not model instructions.
Noul returns a yes probability, without separate confidence. Choice returns selected
option, option probabilities and confidence. Score returns a weighted ordinal value,
legend, probabilities and confidence. Unknown must be modeled explicitly or derived
from uncertainty; it is not a guaranteed provider error field. This output slice uses
independent Choice questions with allow/reject/unknown. It does not falsely normalize
all primitives into the same confidence field.

The API documents 401 authentication, 422 validation, 429 rate limit and 529 overload.
SDK retries are on by default, so this implementation deliberately uses direct HTTP
with no retry. No provider failure is changed to approval.

[API reference](https://docs.typesafe.ai/api), [OpenAPI](https://api.typesafe.ai/openapi.json),
[confidence](https://docs.typesafe.ai/confidence).

## Catalogue, costs, rate and language

GET /v1/models may list only aliases. The docs explicitly permit fixed version IDs
that do not appear in that list. Therefore configured_model_present=false for a pinned
version must not, by itself, become an account-unavailable diagnosis.

Current published Jev 1.13 price is USD 0.042 per million input tokens; output tokens
are free. Reported limits are 100K tokens/second, 80 requests/second, 64K total request
context and 32K state plus longest question. These limits can change. Response usage
has token counts, not currency, balance or a spend authorization.

The model is text-only. English is the strongest supported language; Chinese/CJK need
application-specific evaluation. This is why syntactically valid Chinese replies do
not automatically admit a production review policy.

[Models and language support](https://docs.typesafe.ai/models).

The provider additionally warns about literal reading, indirection, irrelevant context,
adversarial text that steers answers, and choice-order bias. Precise questions, fail-closed
handling and per-effect coverage are engineering controls, not evidence those semantic
weaknesses have disappeared.

[Current model limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).

## Proposed bounded smoke, awaiting parent/user approval

One authenticated model-list GET and at most two POST evaluations, each <=16 KiB JSON,
with a 10-second cooperative deadline and zero retries. Use only hand-authored synthetic
Chinese scene data: one clearly compatible range and one explicit speech-boundary
violation. No private conversations, images, audio or personal facts are needed.

Proposed aggregate TypeSafe charge limit: USD 0.01. Reconfirm current account price and
consent before making the calls. At the currently published price, two full 64K-input
requests are nominally USD 0.005376; actual request token counts are returned by usage.
The local request limit bounds attempts, not the provider's invoice, independent callers
or future price changes. Failure/timeout can still consume provider resources and money.
No call is silently retried. If billing terms are uncertain, stop and ask.

Successful catalogue proves catalogue access only. A successful synthetic evaluation
proves that exact request and wire model work; it does not calibrate Chinese judgment,
prove all account permissions, activate the product factory, or verify speech/image IO.

## Confidence precision correction · 2026-10-03 10:45 UTC

The documented Choice formula is correct, but the former `1e-4` equality assumption
rejected the primary API example and the director's finite-decimal numeric sample.
See [the correction addendum](confidence-contract-correction.md) for source evidence,
the narrowly bounded cent-grid interval policy, unchanged raw-value thresholding,
actual RED/GREEN and the separate connectivity/parser/calibration statuses. The
serialization policy is an explicit compatibility assumption, not a provider promise.
