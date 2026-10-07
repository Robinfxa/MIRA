# IMG-DIAG-02: distinguish returned-image failures without exposing payloads

## Scope
The 2026-10-06 device export records generation_returned followed by operation_failed. That marker is sampled after failure and does not timestamp the generation return. It cannot distinguish returned object validation, PNG decoding, or job timeout.

The baseline is the read-only 1515 source at mira-luna-tool-integration-20261006T1431Z. This change adds closed diagnostic facts only. It does not loosen image acceptance, grant review authority, retry a provider, read credentials, or claim provider qualification.

## Requirements
### IMGDIAG02-001

On image failure, export the last operation stage, fixed failure enum and fixed exception class. Unknown exception text maps to unknown and is never exported.
### IMGDIAG02-002

After a returned PNG header, expose bounded unsigned IHDR width/height, fixed PNG color mode, and fixed bit-depth category. Expose no image, prompt, provider body, or arbitrary exception message.
### IMGDIAG02-003

Generation return, successful pixel review, and qualification remain distinct. Invalid returned type, dimensions, alpha, and CRC never start pixel review.
### IMGDIAG02-004

Job timeout records timeout at the stage already reached, including decode, without claiming a provider HTTP error.
### IMGDIAG02-005

Existing metadata-only exports remain readable. New unknown diagnostic keys and invalid enum values remain rejected.

## Given / When / Then
Given synthetic invalid image bytes and an offline generation port, when the pipeline rejects before review, then it preserves the precise closed failure reason, safe header metadata when present, and zero review calls.
Given the pipeline is decoding when its job deadline expires, when the actor catches TimeoutError, then the exported stage is png_decode and reason is timeout.
Given an old image_readiness event, when the importer reads it, then missing new diagnostic fields receive unobserved defaults.
Given an exception containing secrets, when it is projected, then no exception text reaches metadata.

## Consumers, ownership and checks
Providers owns tests/contracts/test_image_operation_diagnostics.py through tests/quality.toml's unique contract glob. Consumers are StoryImageRuntime, SessionActor image status, image_readiness and metadata export/import. No provider/network resources are used by tests. The actor timeout call is a one-line integration-owner change. Run the new targeted tests RED/GREEN, existing image/readiness/structured-privacy contracts, architecture and affected integration against the shared base.

