# v2 cue-schema migration

This revision changes only explicit nullable cue metadata on existing compiled Effect facts.
It does not reinterpret input, model output, restrictions, obligations, labels or partitions.
All gold remains a draft pending independent adjudication. Thresholds and remaining spend/
request bounds remain unchanged; no scored model run or holdout response was observed.

The entire original v1 artifact set (including its original test implementation) is preserved
under archive-v1, with the original manifest and exact hashes. The historical source receipt
records its then-current code, not admission of current code. v1 files are not rewritten.

Current tests use v2 exact typed serialization. A new immutable live-evaluation source receipt
and resolved label disagreements remain required before scored calls. This schema update is
not a calibration result and cannot create a calibration_ref.

## Pre-run adjudication adoption

The independent AI review agreed60 original/new rows, disputed6, and identified5 no-call guards. Existing labels remain byte-equivalent after stripping only new null cue fields. Disputed rows remain in the corpus but are excluded from the selected diagnostic queue. The reviewed14-item subset is followed by two independently proposed, director-reviewed O2-negative development cases. These additions close the all-O2-allow coverage hole without claiming dimension isolation; overlapping unsupported-fact/character/obligation failures are retained. All16positions remain inside the original20-attempt overall cap, with the same reserve-before-dispatch cost guard. They are not a promise that all16calls fit the remaining budget.

Holdout families have near-paraphrase overlap; they are procedurally unused, not family-independent samples. No broad Chinese safety or calibration admission follows. The dedicated runner will require a final code/question/case manifest before any request.
