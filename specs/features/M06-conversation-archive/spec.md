# Explicit conversation archive and bounded reentry

Baseline: frozen bounded projection 1616Z on delivered 1551. Owner: providers
(existing unique `tests/contracts/test_*.py` ownership in tests/quality.toml).
Consumers: Actor/context, direct/Codex generation, JEV, pairing/bootstrap composition.
No HTTP schema, CLI, generated contract, dependency or network change in this slice.
Test resources are synthetic private temporary databases and injected local workers.
This is a narrow adapter over the existing SQLite ledger schema, privacy filter,
source versions, supersession and tombstones, not a new general memory platform.

### M06CA-001: Three independent authorizations and inert defaults

Given no conversation binding or authorization, no automatic input/receipt archive
is opened or written. The sync/async archive requires a fixed explicit MemoryScope,
path, enabled flag, transcript-persistence authorization, and confirmed local pairing
before open. Existing manual memory, story checkpoint, diagnostic recorder or
transmission flags cannot authorize it. Composition must reject aliasing the manual
memory/story database paths and must supply the real pairing result.

A SessionConversationBinding can record without external recall. Reentry additionally
requires one exact prior session and separate selected-provider/JEV transmission
consent. If real Google TTS is composed, derived recalled speech additionally needs
its own Google consent; Actor also checks this against the injected synthesis port.
Default absent fields preserve legacy wire bytes. Bootstrap/CLI/UI pairing, flags
and public management routes are the integration owner's subsequent work.

### M06CA-002: Exact local evidence, not planned or heard history

Given explicitly enabled recording, the Actor asynchronously captures exact accepted
input identity, source, epoch, index and original text, and only actual software
presentation/audio receipt facts. Generated candidates/accepted-only grants are not
conversation evidence. Full associated speech text can be archived with its explicit
software progress stage, but partial/interrupted speech text is omitted from recall
because samples do not establish spoken words. Completed software audio is still
not physical hearing or understanding. Original maximum-size text is not shortened.

Writes use one worker and one active call; Actor coalesces only immutable snapshots,
which contain all accepted facts, so pending snapshots do not discard an older input.
Exact event retries are idempotent. The worker wait is bounded to five seconds and
remains occupied until a timed-out/canceled call actually finishes. Timeout does not
claim rollback. Binding.persistence_status distinguishes pending, saved, rejected,
unavailable/unknown write outcome and revoked; UI must not show pending as saved.

### M06CA-003: Exact restart and bounded historical recall

Given an authorized archive restart, load_session returns the same effective source
records with IDs, versions, stages and original payloads, only from the fixed scope
and exact chosen session. This does not restore active requests, old permits or the
current physical scene. A new Actor receives recalled history in conversation_recall,
separate from current user_inputs and presented_effects. Up to eight whole source
rows are selected lexically within 8192 bytes, with explicit counts/omissions and no
semantic-summary/completeness claim. Source scope/session identifiers are not sent
in the provider projection. Input-permission JEV omits recalled transcript content;
generation/output JEV may receive it only under the separate authorization.

The 100-turn synthetic Actor test preserves 200 exact input/receipt records locally
including the first source, while the ordinary generation view stays bounded.
Full SQLite history is not automatically dumped to providers.

### M06CA-004: Correction, suppression and revocation

Each accepted source is independent original evidence. Bounded context-marker
chains describe which historical receipts can derive from earlier inputs. Replacing
an input creates a new source version; obsolete ancestors and all dependent receipt
chains become ineligible immediately in one coherent read. Later original user
inputs remain distinct evidence. Forgetting an input or session uses existing
recoverable tombstones; it is not physical deletion. An exact old capture retry
cannot revive suppressed or superseded evidence. No cached semantic summary exists.

These operations change archive eligibility, not the already accepted in-process
Actor ledger. They do not claim the current conversation has fully forgotten text
already sent to a provider. An interface offering whole-conversation forgetting must
also close/reset the active session and disclose provider-retention boundaries.
Binding.revoke immediately stops new recording/recall and fences already recalled
output; an in-flight previously authorized write may still commit. Previously stored
records remain local until an explicit suppression/management action. Closing the
session flushes accepted evidence where possible without pretending failures saved.

### M06CA-005: Scope, version, privacy and cancellation fences

Stored source structure and source classes are validated. Known credential-like text
is rejected by the existing privacy guard before transcript persistence, which is
not a universal secret detector. Wrong session/scope, malformed records, denied
access and revoked authority fail closed. Operational archive absence can continue
one ordinary model generation with explicit no-recall status, without a hidden call.

Recalled source-session revisions are rechecked before grants and delayed speech.
Current-session recording does not itself stale a prior-session packet. Corrections
or suppression during generation prevent recalled output acceptance. Stop/new input
never waits on archive IO; a late read that suppresses cancellation cannot overwrite
the latest context, call the generator or revive output.

## Verification limits

No real user database, credentials, provider, Google service or account was used.
Local synthetic software receipts do not establish actual audio/visual perception.
Natural-language summary quality, automatic recognition of correction/forget intents,
public archive-management UI/CLI, and final paired entry wiring are not implemented
by these modules. Whole original accepted data is retained only in explicitly enabled
local archives; default sessions remain in-process and bounded by existing runtime
limits. No second summarizer, service or external index is added.

A separate resource RED reproduced an inherited pytest policy-loop orphan in the
legacy story-checkpoint tests. The synchronous asyncio.run wrappers in six affected test files now use pytest-owned
async functions with unchanged assertions and cleanup; no warning is filtered.
