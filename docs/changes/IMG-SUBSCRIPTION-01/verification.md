# IMG-SUBSCRIPTION-01 offline verification

Base is the immutable 1292-file mira-combined-next-20261006T0018Z capture (manifest SHA-256 8739c3c84c5628bae4a6a3b5a38fcbff8ae49ba35a48c9cabedc42612899d209). This isolated source is mira-subscription-image-20261006T0042Z. The API adapters, ports, PNG decoder and runtime remain unchanged. New files are the subscription image adapter, narrow shared auth-header helper, one provider-owned contract test module, spec/traceability and this record. No dependency changes.

Synthetic-only interpreter: existing mira-image-runtime-20261005T2253Z/.venv/bin/python. Evidence is append-only outside the checkout in mira-subscription-image-evidence-20261006T0045Z.

- 001-red: exact-request/identity/gzip group failed twice on explicit unimplemented generation behavior, not collection/import failure. Stub source and test SHA-256 retained beside the output.
- 002-red-full: same complete test module, 73 failed and 14 passed in 10.87s.
- 003-green-full: unchanged complete test module, 87 passed in 1.04s. Tests include real gzip bytes, fixed subscription destination, source-derived DTO shape, safe credential failures, no paid API fallback, exact-count/base64 limits, downstream strict PNG rejection, and swallowed cancellation/deadline across credential resolution, HTTP handling, body and cleanup.
- 004-red-metadata / 005-green-final: review identified that default Rust serde ignores bounded benign extra metadata and ImagesClient does not require a MIME header. Three positive compatibility controls failed before repair; 14 explicit-failure controls already passed. The repaired complete suite passed 104 cases.
- 006-red-passive-hints / 007-green-final: valid inline PNG with auto hints and passive URLs first failed, then passed without fetching or trusting the URLs. The complete suite passed 103 cases in 1.19s; the count changed because two overstrict URL-presence negatives were replaced with one compatibility positive. Actual downstream PNG dimensions/opacity remain authoritative.

The downstream decoder remains the existing maintained Pillow implementation and all resource/presentation admission is still separate. Explicit request values size=1024x1024/n=1 constrain the first-party DTO but differ from native Codex's auto/omitted defaults; private-backend acceptance is unknown. Public third-party plan usage currently excludes images. No live model, account entitlement, charge, browser or device acceptance is implied. All live requests, authentication-store access, installs, full/release checks and publication are not run in this slice.

The integration handoff includes the explicit changed-file affected report and a SHA-256 manifest/patch against this immutable base. Affected evidence must be read for its own final status; 87 focused passes are not an aggregate or integrated release result.
