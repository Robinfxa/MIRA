# WP01 JEV output o3 completion-claim question v2

Status: narrow question-set revision. This is independent of threshold policy
`user-development-0.6-v2`; it does not change thresholds, authorization, other review
dimensions, or deterministic guards.

`QUESTION_SET_VERSION` stays `mira-output-v1` and remains the constructor default. The
backend accepts `question_set_revision="mira-output-v2"` only when explicitly selected;
threshold policy selection never chooses the question set. The v1 wording remains
available byte-for-byte for historical evaluation.

## Given / When / Then

### WP01JEVO3QUESTIONV2-001 Scoped positive o3 criterion

Given a complete output candidate with typed speech/subtitle and optional controls, when
o3 is asked whether past completion is supported, then it evaluates only completed
factual claims in speech/subtitle text. Allow means all such claims are supported by
matching actual evidence in `presented_effects`, or there are no such claims. Unsupported
completed claims fail. Future intentions and typed pose/scene/media candidates are pending
proposals, not completion claims and not evidence for completed-history statements.
Ambiguous claim scope or evidence matching remains unknown. The input is evaluated in its
original Chinese as written.

### WP01JEVO3QUESTIONV2-002 Preserve evidence and request bindings

Given the versioned output question set, when a request is built, then its complete typed
context, candidate, contract, original input, `presented_effects`, `accepted_prefix`, all
contract evidence and all digests remain bound. The canonical request digest includes the
explicitly selected output question-set version. V1 remains the default, v1 and v2 are the
only accepted revisions, and threshold policy cannot implicitly choose v2. Accepted-only
evidence does not become presented or completed history. No old question-set evidence is
rewritten.

### WP01JEVO3QUESTIONV2-003 Other policy and guards remain independent

Given a supported threshold policy, when responses are parsed, then the configured
policy's existing outcome handling is preserved. The question-set identity is separately
versioned from the threshold policy. A future intention that violates an explicit ban can
pass o3's completion-only condition but must still be blocked by the existing constraint
or other review path. Existing control, media, Stop, permission, and fallback guards remain
in force.

## Verification boundary

Synthetic transport tests verify exact question bytes, full state/digest binding, parser
and configured policy routing only. They cannot show that a live JEV model understands the
Chinese examples or that wording caused any observed label.
