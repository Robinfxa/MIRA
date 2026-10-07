# WARDROBE-01: closed local wardrobe diagnostics

Baseline: frozen 0542 capture manifest 708e5bd5111fa5b24fb8a23ef4519b6b50efe352840355dbc7601112ad02d599. Owner: isolated wardrobe diagnostic slice. Necessary surfaces: session_actor, diagnostic event contract and privacy serializer. No HTTP/DTO/domain-state or prompt changes. Provider test ownership: existing tests/contracts/test_*.py glob in tests/quality.toml; actor/config/http consume the actor and diagnostics. Existing Python environment only, directed checks and affected checks, jobs at most 3. No provider, device, account, real database, installation, budget, or art work.

- Given no generated wardrobe pose versus an unavailable authored wardrobe pose, when character preparation runs, separate candidate and readiness records distinguish absence from removal.
- Given a surviving pose, review allow/hold and actual issued grant are separate facts. No grant is inferred from text. Same-current-outfit is not a failure.
- Given Stop/supersession during review or before receipt, record cancellation without reviving late work. A domain-validated late pre-fence receipt is historical presentation, never new authority; invalid receipts emit no presented record.
- Given a valid receipt, record the exact existing effect correlation and subsequent context's current/acknowledged outfit. Diagnostics remain local and do not enter generation/review facts, story memory or dialogue.
- Every new payload permits only the three existing outfit controls, closed stage/state/reason, bounded counts/epoch/activity and existing correlation IDs. Unexpected strings/fields, arbitrary pose names and raw/digest/prompt data fail strict export validation. Existing event records remain accepted with no skipped records.

Tests: tests/contracts/test_wardrobe_diagnostics.py. Directed RED/GREEN evidence is recorded separately; no claim that missing poses in the uploaded historical session have acquired a proven original cause.
