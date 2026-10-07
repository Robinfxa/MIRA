# STORY-IMAGE-OPTIONS-01 completed offline tasks

- Default-disabled immutable options and safe no-client declaration.
- Explicit story + official image API route + exact model/quality + separate recipient/spend consent.
- Finite process job counts, output/wire bytes, whole-job/provider durations and planning reservations.
- Existing OpenAI loader settings used only when image capability is enabled; no auth fallback/discovery.
- One small shared process gate through the runtime's optional ImageOperationAdmission hook; session state remains separate.
- Launcher check and serve wiring preserve text provider and Fast behavior.
- Synthetic directed regression checks, matching real constructor smoke, affected-scope verification and documented limitations.

Deferred to integration owner: same-tree combined runtime/adapters/bootstrap review and verification. Deferred to separately approved live work: actual API/image/review/receipt quality, with exact data/model choices and estimate-versus-hard-cap disclosure. Arbitrary user image briefs and private canon/memory transmission are not implemented by this catalog slice.
