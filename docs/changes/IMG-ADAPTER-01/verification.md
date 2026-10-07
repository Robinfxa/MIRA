# IMG-ADAPTER-01 offline adapter verification

Frozen source slice: mira-story-image-adapters-20261005T2252Z, based on frozen mira-integration-20261005T2238Z. The runtime owner's media port and story-image domain files were copied read-only solely to compile this partial slice; neither belongs to this adapter integration delta.

Implemented five adapter files: media/__init__.py, _openai_http.py, openai_images.py, openai_vision_review.py, png_decoder.py. Explicit OpenAI API key/model/options injection; fixed official Images and Responses endpoints; no registration in bootstrap, no model/default-route fallback, no environment/credential discovery. One PNG generation result is bounded and canonicalized before independent exact-pixel review. Canonical pixels, request, specification and policy are bound; observations do not issue a presentation permit. Safe fixed errors, finite timeouts, cancellation propagation, no automatic retry. Calls and byte limits are not a hard dollar billing cap.

Test owner is the existing providers lane's tests/contracts/test_*.py glob. No quality.toml change or new shared owner was needed.

## Actual records

- 001-red-contracts: 82 failed, process exit 1, before implementation behavior stubs. This was executable contract failure, not a missing import or dependency collection error.
- 002-green-contracts: same test-file hash, 82 passed, process exit 0, after implementation.
- 003-red-canonical-hardening: 3 failed and 92 passed, process exit 1. Tests exposed noncanonical review dispatch, opaque RGBA refusal, and allowed global truncation tolerance.
- 004-green-canonical-hardening: same test-file hash as 003, 95 passed, process exit 0, after the three fixes.
- 005-spec-links: 370 inherited/new requirements point to collectable test nodes, process exit 0. This is mapping validation, not 370 executed behaviors.

Every record reports zero source changes during execution and retains stdout/stderr hashes. Do not add the pass counts across stages. Evidence is under docs/verification/img-adapter-01/runs/. Final contract-test SHA-256: b5eaa1d06efdec122b3f60f222b523a5791e2c742b41769e607fd6e4fadda2da.

The director provisioned the separate image-test Python environment with the original dependency lock plus official hash-verified Pillow 12.3.0. Final GREEN interpreter: /workspace/scratch/96ff05e059bf/mira-image-runtime-20261005T2253Z/.venv/bin/python. Original runtime was not changed by this adapter slice. Dependency version and provenance are recorded separately.

## Covered boundaries

Synthetic HTTP checks cover exact bounded request bodies and selected endpoints; n=1/PNG/1024/opaque; absence of private session/resource context; unsafe references, multiple outputs, invalid base64, response wire/decoded limits, duplicate JSON keys and invalid constants; compressed/mislabeled/redirected/rate-limited/error responses; incomplete/refused/tool/multi-message review; request/spec/pixel/policy binding; failed and unassessable checks; transport cancellation and finite deadline; explicit model/quality/token options and rejection of raw/OAuth credential shapes.

Synthetic PNG checks cover full maintained-decoder load, CRC/truncation including truncated deflate, byte/dimension bombs, wrong dimensions, animation, trailing content, metadata removal, idempotent canonical bytes, preservation of RGB pixels, opaque alpha normalization, nonopaque alpha rejection, and refusal of permissive global decoder settings. Review refuses noncanonical or mislabeled pixels before any HTTP call.

## Deliberately unverified here

No provider/auth/model calls, real user content, real photo, generated repository art, live API authorization, live billing limit, browser display, device behavior, or visual-review accuracy was exercised. Public official documentation was read. Live activation still requires the director's explicit composition and separate route/model/data/budget consent. The director owns the merged candidate's affected/full/package/release and independent audit; a partial-tree aggregate was not run after instruction to freeze. The adapter slice's stale copied domain allowlist discrepancy is left to that integrated runtime contract, not patched here.
