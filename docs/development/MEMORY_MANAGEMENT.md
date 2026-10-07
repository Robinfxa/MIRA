# Explicit local memory management (next-stage candidate)

This candidate adds a secondary management panel to the paired text-memory app.
Its focused software tests passed; read the matching complete delivery
acceptance record before using it. Published1515 remains an immutable read-only Actor-recall delivery.

## Three separate choices

1. The memory CLI's local storage consent controls manual records in the private
   store. This is not consent to send them to a provider.
2. `--authorize-memory-to-codex-and-jev` names the recipients for selected
   evidence in later text turns. It does not authorize local edits.
3. `--authorize-local-memory-management` permits manually confirmed operations
   in the paired panel. It does not enable automatic transcript extraction or
   expand provider permissions.

The first panel version belongs to the explicitly configured, paired text-memory
entry (`tools/live_dev.py`). Add the third flag to the existing memory-mode
arguments only if you want editing. `check` creates no pairing code, opens no
store, and performs no operation. `serve` still requires the one-use local
pairing flow. No option authorizes another browser or chooses a scope from HTTP.

## What each operation means

- Save: type the exact statement and choose ordinary optional-recall memory or
  an explicit boundary that must be retained in each context packet. Review and
  confirm it before submission. Ordinary preferences normally belong in optional
  memory, not in the mandatory-boundary category. Long or numerous boundaries
  can exceed the context budget; the app then refuses that turn instead of
  silently dropping them. Use correction or reversible forgetting to revise
  the local record deliberately.
- Correct: append a new version; the superseded text remains in local history.
- Forget: hide the selected statement from recall with a reversible tombstone.
  This does not physically erase its text or undo a previous transmission.
- Restore: explicitly reverse an active soft-forget event.

The operation itself is local. If recall transmission is enabled, later turns
may send selected saved records to Codex generation and TypeSafe/JEV output
review. Do not store credentials. Recognized credential-like content is refused;
this heuristic is not a guarantee that every possible secret will be detected.
There is no automatic summarization, personality learning, or automatic saving
of character output, microphone content, or generated images.

## Conflicts, Stop, and uncertain outcomes

Each mutation carries a displayed scope revision and a unique operation ID.
A changed revision fails instead of silently overwriting another change. The UI
never automatically retries an edit. If a response is lost, an explicit
reconciliation reuses the same ID and exact body, rather than creating a second
operation. A committed append may finish before cancellation; the UI must not
claim it was undone solely because Stop, close, or an aborted request happened.

Stop remains local-first for character output and cancels unsubmitted panel
confirmation. Revoke ends the paired operator authority and closes memory
resources. The Actor's existing revision check prevents new grants from a
candidate built on a changed store; already presented history is not rewritten.

## Scope and privacy

The local startup configuration fixes the database and user/character/world
scope. The panel cannot choose paths, other users, evidence-source authority, or
presentation receipts. Only manually entered USER_STATEMENT evidence is managed.
Other source classes are not exposed. Listing and edits are bounded. Default
logs and diagnostic exports exclude record text, pairing codes, credentials and
private database contents. The database remains outside Git and delivery packs.

The localhost capability is not multi-user identity authentication and does not
protect against malware running as the same OS user or a compromised paired
browser. This stage is verified with synthetic records and fake transports only;
no real user memory or provider call is part of its automated tests.
