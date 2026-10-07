# Optional local conversation recording and selected reentry

This candidate wires the existing exact-input/software-receipt archive into the
direct application. It is separate from hand-written memory, authored story
checkpoints, diagnostic transcript recording and microphone recording. Default
startup opens no conversation database and records no conversation.

## Start deliberately

Create an owner-only private directory outside the checkout and choose a dedicated
SQLite filename there. The parent directory must already exist and be mode 0700.
Reuse the existing private scope file format from LOCAL_MEMORY.md, selecting one
alias locally. Existing scope files/databases must be owner-only regular files;
symlinks, hard links, paths within the checkout and aliases of configured manual
memory/story databases are rejected. The browser cannot choose a path or scope.

Append these options to the existing tools/live_provider.py check or serve command:

```
--conversation-db /absolute/private/conversations.sqlite
--conversation-scope-config /absolute/private/scopes.json
--conversation-scope YOUR_LOCAL_ALIAS
--authorize-conversation-persistence
--create-local-operator-pairing
```

The recording choice authorizes accepted text/final transcription and actual
software presentation/audio-progress receipts. It does not authorize raw audio,
provider recall, Google-derived speech or changes to hand-written memory/story.
Check reads only bounded scope metadata and file metadata. It creates no database,
pairing credential or frontend output, and makes no provider request.

Serve uses the existing one-use local pairing file. Only after pairing does it
open the fixed database. No new credential format or account is introduced.
Before chatting, the paired page shows recording status, lets you inspect a
specific historical session and offers “no history recall.” Selected recall needs
a separate checkbox naming the selected OpenAI route. Default `luna_tools` mode
constructs no JEV reviews and sends no archive evidence to JEV. An explicit
`--action-review-mode legacy_jev` also discloses TypeSafe/JEV output review. Voice additionally needs its own Google Cloud TTS derived-speech checkbox.
The microphone still requires its existing gesture/browser permission.

You can instead explicitly preselect a known prior session at launch:

```
--recall-conversation-session EXACT_PRIOR_SESSION_ID
--authorize-conversation-to-selected-provider
```

The old `--authorize-conversation-to-selected-provider-and-jev` flag remains a
compatibility alias; it does not turn on JEV in the default mode or expand the
selected session/scope.

With voice also add --authorize-conversation-derived-speech-to-google. Selecting a
history without the applicable separate consents fails. No “latest session” is
chosen automatically. The selected source is fixed once chat starts; restart and
pair again to change it. The current Actor's permissions, active effects, input
ledger, listening state and scene are not restored from history.

## Local correction and forgetting

Add --authorize-local-conversation-management to expose confirmed local input
correction, soft-forget and restore controls. Each change shows its target and
requires an explicit checkbox. It uses the same revision checks and idempotent
operation IDs as the existing local-memory editor. An uncertain response retains
that operation ID for reconciliation; do not create a duplicate mutation.

The source list includes retained old correction versions. To reverse a wording
change, correct the current version using the chosen retained old wording. Forget
is reversible suppression, not physical deletion; its dedicated restore button
reverses that particular tombstone. Receipt facts cannot be rewritten as accepted
inputs or fabricated by the management endpoint. Page reads are bounded to 20
items and 64 KiB of source content, with revision-bound cursors.

Correction/suppression changes future archive eligibility. It does not erase
current in-process accepted inputs, information already sent to providers, or
sound already played. Derived rows retain the exact historical source entry IDs/versions used by their
generation epoch in local-only provenance. Correction/forget suppresses their
future recall across session chains, including later replies in the same session
that could use earlier recalled output. Independently accepted inputs and raw
historical receipt facts stay locally retained. This is conservative eligibility,
not semantic erasure. Archives created before provenance tracking cannot acquire
unrecorded historical source relationships retrospectively.

## Status and stopping

The panel can refresh enabled/no-committed-records, pending, saved, unavailable,
rejected, unknown-write-outcome and revoked states. Saved means local storage
confirmed completion. A software receipt does not establish physical hearing or
understanding; partial audio shows measured software progress and labels its full
associated text as a plan, not words known to have been heard.

An ordinary operational archive failure stays visible and ordinary chat can run
without recalled content. Missing consent, invalid scope/source or revocation do
not silently authorize sharing. “Revoke” stops future capture/recall immediately
and retains existing local records. An already-running authorized write may still
commit. Stop cancels interaction without claiming to undo storage. Ending pairing
closes the runtime; the one-use code cannot reopen it.

This stage is verified with synthetic SQLite, ASGI, fake provider ports and the
compiled browser module. It does not establish real-provider conversational
quality, complete M06, semantic summarization, automatic fact extraction, learned
personality, physical hearing or user-device acceptance.
