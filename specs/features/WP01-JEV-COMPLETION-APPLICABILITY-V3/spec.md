# WP01 JEV output completion-claim applicability v3

Status: versioned development-review question-set change. The v1/v2 output request
and response contracts remain supported without reinterpretation. This change does not
alter policy thresholds, permissions, provider admission, calibration, or live quality.

## Given / When / Then

### JEVCOMPAPPV3-001 Versioned request and one-batch tri-state applicability

Given the explicit `mira-output-v3` question set, when output review is sent, then one
NOUL question asks whether candidate speech/subtitle text asserts already-completed
facts, in the same request batch as the existing O1–O6 and effect questions. Typed
pose, scene, and media fields are pending proposals rather than proof of historical
events. The question-set revision, contract, and request digest bind v3 explicitly;
v1 and v2 bytes/contracts remain unchanged.

### JEVCOMPAPPV3-002 Only clear NO scopes out O3 aggregation

Given a fully valid v3 response, when the applicability probability is at most 0.4
(equivalently, 1 minus that probability is at least 0.6), then only O3's semantic
verdict is excluded from final aggregation. YES and UNKNOWN continue to use the original
O3 answer. Every other question, including explicit constraint review, remains in
aggregation. No deterministic ban, permission, control, stop, or evidence gate is
relaxed, and UNKNOWN is never converted into ALLOW.

### JEVCOMPAPPV3-003 Full wire validation and product default

Given a v3 response, when any expected question/answer is missing, unexpected, wrongly
typed, boolean/non-finite/out-of-range, or otherwise malformed, then the entire response
is a technical contract error even if applicability would otherwise be NO. Product
development assembly explicitly selects v3 while callers can still explicitly select
v1/v2. Synthetic direct-adapter and ASGI tests establish mechanics only; they do not
establish provider quality or production readiness.
