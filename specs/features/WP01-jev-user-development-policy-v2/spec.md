# WP01 JEV user-selected development policy v2

Status: narrowly versioned development-policy correction. This is not calibration,
statistical-quality evidence, provider permission, or a default-provider change.

Scope: `user-development-0.6-v2` is an immutable typed opt-in for existing JEV input
and output adapters. V1 retains its historical low-confidence REJECT behavior exactly.

## Given / When / Then

### JEVDEV06V2-001 Exact version recognition

Given an exact supported immutable v1 or v2 policy, when it is supplied to an adapter,
then only that exact bundle is accepted and its version is preserved in observation
provenance. Altered threshold bundles and unknown versions remain rejected.

### JEVDEV06V2-002 Output uncertainty in both directions

Given a complete, well-formed output review, when a selected ALLOW or REJECT has either
selected probability below 0.6 or confidence below 0.6, then return semantic UNKNOWN.
Only an ALLOW with both statistics at least 0.6 may become ALLOW; a REJECT with both
at least 0.6 may become REJECT. A well-formed UNKNOWN label stays UNKNOWN. A weak REJECT
uses the existing deterministic system clarification fallback and produces no grant.

### JEVDEV06V2-003 Preserve input gates and fail-closed restrictions

Given the existing input adapter, when v2 is selected, then NOUL probability direction
and 0.6 / 0.4 thresholds stay unchanged; exact referent, evidence, permissions, local
Stop, snapshot/contract binding, schema validation, and deterministic restrictions stay
fail-closed. UNKNOWN never becomes ALLOW.

### JEVDEV06V2-004 Historical v1 behavior

Given the v1 policy and unchanged request/response inputs, when evaluated, then its
existing labels, thresholds, observation provenance, receipts, and tests keep their
historical meaning. No historical v1 evidence is rewritten as v2 evidence.

## Verification boundary

Synthetic transports and an ASGI synthetic session prove only policy mechanics and
fallback routing. They do not measure language quality, calibrate a model, or establish
production readiness.
