# STT diagnostic milestones

The existing safe diagnostic sink may emit three fixed server-side speech recognition milestones: first provider revision, first final provider revision, and provider stream end. Each event contains only a controlled stage name, correlation context, outcome, and nonnegative elapsed `duration_ms` from the existing STT span; it has no transcript, PCM, credentials, headers, or arbitrary metadata. Client `performance.now()` durations stay separate from server `monotonic()` durations and are never subtracted across processes.

## Requirements

### WP03STTDIAG-001: numeric milestones only
Given fake transcript revisions, when a media operation processes an STT stream, then the existing diagnostics sink emits first-revision, first-final-revision, and stream-end stage observations exactly once with numeric durations and no transcript text. Non-STT media and observations never change stream or cancellation behavior.

## Verification scope

Owner: providers lane (`tests/contracts/test_*.py`). Resource: synthetic transcript source and in-memory diagnostic sink only. No provider or paid call.
