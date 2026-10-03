# WP01 JEV user-selected development policy

Status: explicit local development decision policy. This choice is not a calibration
reference, measured production quality, or permission to enable a provider.

Scope: `user-development-0.6-v1` is an immutable, typed opt-in for the existing JEV
output and input adapters. The default unconfigured path remains fail-closed; the
historical WP01 production/calibration and evaluation policies retain their original
meaning and evidence.

## Given / When / Then

### JEVDEV06-001 Explicit policy provenance

Given a developer explicitly selects the recognized versioned policy,
when JEV observations are parsed and consumed,
then provenance is `user-development-0.6-v1`, `calibration_ref` stays absent, and the
application may consume a complete validated observation without claiming calibration.
An unsupported policy ID or altered threshold bundle is rejected. No selection leaves
the existing default/calibration behavior unchanged.

### JEVDEV06-002 Output Choice thresholds and labels

Given an exact, current, schema-valid, complete response,
when all required selected answers are `allow` and each selected probability and
reported confidence are both at least 0.6,
then the development-policy review may return ALLOW without a calibration gate.
Any selected `reject` remains REJECT regardless of its confidence; selected `unknown`
remains UNKNOWN even at high probability/confidence. The same selected user policy does
not inherit the historical 0.99 / 0.985 admission thresholds.

### JEVDEV06-003 Explicit input prohibitions and referents

Given a valid input question set and response,
when a prohibition predicate has `p(yes) >= 0.6`, interpret it as YES/prohibition;
when `p(yes) <= 0.4`, interpret it as NO; otherwise leave it UNKNOWN. Noul has no
fabricated confidence. A controlled referent additionally needs selected probability
and reported confidence at least 0.6, an unambiguous selected identity, and evidence
that the exact object was actually presented. Application validation uses the same
exact-or-cent-grid interval compatibility check as the input adapter, while the 0.6
gates use original reported values. Incompatible rounded values such as 0.72/0.60
remain invalid; compatible 0.73/0.60 values can proceed. High scores cannot invent
unseen objects.

### JEVDEV06-004 Existing safeguards

Given this development policy is selected,
when strict wire validation, request nonce/content binding, stale snapshot checks,
local Stop, explicit speech/photography restrictions, or controlled-effect checks apply,
then those existing safeguards keep their prior behavior. The threshold policy creates
no permit, permission, provider call, account change, or automatic factory activation.

## Verification boundary

Tests use injected synthetic transports only. They establish adapter mechanics for the
selected development thresholds; they do not recalibrate or modify historical Chinese
quality results and do not establish production readiness.
