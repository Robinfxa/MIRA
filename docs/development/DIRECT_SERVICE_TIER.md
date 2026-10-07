# Direct requested Fast tier (FAST-01)

The user approved Fast as the default after disclosure that subscription included usage is 2.5 times Standard. The default is restricted to `chatgpt_subscription` + `gpt-6-luna`. It requests `service_tier: "priority"`. This does not change model, reasoning, JEV policy, voice, request budgets, retries or the API billing boundary.

`--service-tier standard` opts out. For the subscription route, Standard omits the field, matching the first-party Codex request builder. `openai_api` and other subscription models still omit the field when the option is absent; explicit API Standard sends `default` and explicit Fast sends `priority`. No automatic catalog lookup or fallback is performed. `/fast` in another Codex process does not configure MIRA.

## Verified wire evidence

Read on 2026-10-05, pinned OpenAI Codex commit `b4e3726d73a34e7906715464cad4d801326f2483` (22:42:17 UTC), via the GitHub connector. These are client source facts, not evidence of MIRA account entitlement or private-backend support:

- [Fast request value](https://github.com/openai/codex/blob/b4e3726d73a34e7906715464cad4d801326f2483/codex-rs/protocol/src/config_types.rs#L528): Fast maps to `priority`; the Standard sentinel is `default`.
- [Explicit Standard filtering](https://github.com/openai/codex/blob/b4e3726d73a34e7906715464cad4d801326f2483/codex-rs/protocol/src/openai_models.rs#L1005): explicit Standard is removed before transport. The [first-party regression test](https://github.com/openai/codex/blob/b4e3726d73a34e7906715464cad4d801326f2483/codex-rs/protocol/src/openai_models.rs#L1965) checks that omission.
- [Serialized request](https://github.com/openai/codex/blob/b4e3726d73a34e7906715464cad4d801326f2483/codex-rs/codex-api/src/common.rs#L279): the field is `service_tier`; an absent option is omitted.
- [Request construction](https://github.com/openai/codex/blob/b4e3726d73a34e7906715464cad4d801326f2483/codex-rs/core/src/client.rs#L979): the resolved service tier is used in the Responses request.
- [Subscription route](https://github.com/openai/codex/blob/b4e3726d73a34e7906715464cad4d801326f2483/codex-rs/model-provider-info/src/lib.rs#L427): ChatGPT auth uses the Codex backend base URL.
- [Subscription speed and usage](https://learn.chatgpt.com/docs/agent-configuration/speed) and [public API Fast mode](https://developers.openai.com/api/docs/guides/fast-mode). The subscription usage multiplier is not a speed guarantee or an API price multiplier.

## Reading the diagnostics

`check` and startup print the requested choice, wire value and `provider_confirmation: "not_run"`. The adapter emits one bounded `service_tier` diagnostic per generation attempt to the startup terminal. It includes the requested choice, actual wire value, provider-reported terminal tier, outcome and a closed reason. No text, account ID, response ID, headers or credentials are included.

Only a successfully completed response with final `response.service_tier` equal to `priority` or `fast` sets `fast_confirmed: true`; the exact returned value remains distinct. The public Fast documentation identifies these as equivalent processing names, while the pinned Codex request source still sends `priority`. Missing/null metadata is `absent`; an unrecognized string is `unknown`; a non-string is `invalid`. Those optional metadata cases preserve valid content and never confirm Fast. A returned `default` remains visible as `default` with an unconfirmed notice. Created/in-progress metadata is not final evidence. None of this is a latency measurement or a billing receipt.

Known provider errors pointing at `service_tier` carry `service_tier_rejected` and recommend an explicit Standard restart. Generic 400/422, auth, quota, timeout, cancellation and malformed-stream errors preserve their original failure classification. Error-body diagnosis reads only that same response, at most 16 KiB and 0.5 seconds inside the existing turn deadline. No automatic retry, tier fallback, route fallback or extra request occurs. Optional diagnostic callback failure cannot turn valid content into failure. Old exported diagnostics remain readable.

## Bounded user-local acceptance (not run here)

Use the user's existing MIRA environment file and independent MIRA login on their own computer. Do not copy Codex credentials. No new key, grant or account setup is needed for this check if the existing MIRA login remains valid. Replace `/absolute/path/mira.env` below with the already selected private file and use the installed application's Python interpreter.

First run the offline declaration:

```sh
python tools/live_provider.py check --provider chatgpt_subscription --model gpt-6-luna --env-file /absolute/path/mira.env --generation-requests 1 --turns 1 --input-jev-requests 1 --output-jev-requests 1 --boundary-max-requests 0
```

It must show requested Fast, wire priority, multiplier 2.5, no provider confirmation and no inference. Start one bounded text-only process:

```sh
python tools/live_provider.py serve --provider chatgpt_subscription --model gpt-6-luna --env-file /absolute/path/mira.env --authorize-provider-data --generation-requests 1 --turns 1 --input-jev-requests 1 --output-jev-requests 1 --boundary-max-requests 0
```

Open the printed loopback URL, send one short non-private sentence once, note time to visible text and the safe `service_tier` line, then stop the server. No voice, story or memory option is needed. The ceiling is one generation and at most two JEV requests for this process; it is not a money cap. Do not restart repeatedly after a failure.

For the authorized small Standard comparison, start the same bounded command once with `--service-tier standard`, submit the same sentence once, and stop. Across the pair: at most two generations and four JEV requests, with only the Fast request using the requested elevated subscription tier. The sample checks reachability and reported tier; two timings cannot establish a reliable speedup. If the tier is absent or unknown, record “requested, unconfirmed,” even if text appears quickly. If rejected, preserve the safe error class and use Standard explicitly; do not silently fall back or switch to API billing.

No real login, provider call, private auth read, user-device check, tier entitlement check or latency experiment was performed in this implementation task.
