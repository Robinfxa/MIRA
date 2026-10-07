# Retained utterance acknowledgment

The1355 backend correctly waited for a drained utterance to be consumed before
starting another RPC, but a UI playback-overlap hold never consumed it. New speech
then remained queued until the lease ended. An actual frozen1355 ASGI reproduction
failed with max_duration; this was a release blocker despite earlier resource tests.

The narrow repair adds exact lease/utterance/revision hold acknowledgment. It keeps
the old text without an Input binding, model turn or episode and permits bounded
continuation only after the success frame is sent. Duplicate active holds return
the same snapshot without another start; mismatched identities and revoked leases
reject. A held token cannot subsequently become an automatic commit. New activity
still commits only its own suffix, including when retained old text has no offsets.
A failed acknowledgment cannot start RPC2, refund a request or erase observed text.

Actual protocol RED→GREEN uses production Google DTOs/adapters/budget wrappers and
ASGI: hold old missing-offset text, acknowledge once, continue exact PCM intoRPC2,
submit only the new text, replay hold idempotently, reject altered identities and
old-token commit, and preserve both request count2 and retained old text. A second
ASGI negative case fails acknowledgment and confirms onlyRPC1 exists, no input was
created, and observed text remains. These are synthetic software results, not
real microphone, paid provider, physical playback or acoustic acceptance.

Evidence is append-only outside source at
`mira-continuous-hold-evidence-20261005T1359Z`; frozen1355 remains unchanged. The
frontend owner is adding the exact control and its retained-text presentation.
Final combined UI/ASGI acceptance and merged release checks remain separate.

The same-RPC boundary also distinguishes one unresolved activity from one activity
total. A previously committed strictly offset-covered snapshot does not prevent a
later missing-offset activity from draining. A production-SDK ASGI case covers
strict first turn→second missing-offset held turn→ack→new RPC fresh input, while
its grace-only predecessor counterexample remains a visible manual fallback.
