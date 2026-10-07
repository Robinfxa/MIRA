# IMG-CHECK-01: bounded local subscription image component check

Owner: providers (tests/contracts/test_subscription_image_check.py, existing unique glob).
Consumers: the explicit local tool only; no server, bootstrap or default test invocation.
Base: mira-combined-next-20261006T0018Z, exact 1292-file capture manifest at
mira-combined-evidence-20261006T0018Z/capture-manifest.json. Adapter and factory
overlays are bound separately in the append-only validation receipt.

### IMGCHECK01-001: disabled until explicit consent

Given no --run, when invoked, emit a configuration-only unverified result with
zero credentials and network activity. Given --run, both fiction data-to-OpenAI
and subscription usage acknowledgements and a review model are required before
auth-source construction. An optional absolute --auth-store selects only an
existing MIRA store. No CLI auth, API key, environment file, login, new grants,
credential copying, arbitrary prompt, URL, input file or reference image option.

### IMGCHECK01-002: one production image and at most one pixel review

Use the existing factory, StoryImageRuntime and one-job process admission; compile
only authored_lighthouse_coast from the existing finite catalog. Count admission
and calls before awaiting. Keep all existing byte and timeout ceilings; one image
generation at n=1 followed only on valid canonical 1024x1024 PNG by one independent
actual-PNG review. Unknown/rejected/invalid reviews fail closed. No retry/fallback.

### IMGCHECK01-003: safe observability and termination

Emit only stage, closed safe category/detail codes, route/model names, status, local admission and
attempt/HTTP counters, and HTTP status integers. Never echo provider metadata,
raw exceptions, bodies, auth, headers, prompts, paths, base64 or generated content.
Specific details use exact enumerated production error codes only, never prefixes;
unknown exceptions become unknown. Preserve counts through auth failures, HTTP failures, malformed image, timeout and
cancellation. CLI exit 0: check-only or successful component; 2: configuration;
1: failed component; 130: cancellation. Passed component does not establish full
scene acceptance, entitlement, plan quota, dollar cost or user-visible display.

## Resources and validation boundary

Offline production parsers and httpx mock transports only. Reuse installed image
runtime .venv; no dependencies installed, live requests, private reads, full/release,
children or automatic invocation. Tests use synthetic pixels and fake opaque auth.
