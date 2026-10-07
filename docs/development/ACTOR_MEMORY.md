# Opt-in local memory in the text application

Status: focused synthetic SQLite, Actor, application and provider-transport
checks have passed. Independent and complete release acceptance belong to the
matching source snapshot and START-HERE; this document is not a live-provider
or user-device acceptance receipt. Published1515 includes this application-recall
implementation; its exact full-release receipt remains with that immutable pack.

## What changes

The local memory CLI records, corrects, reversibly forgets, or restores explicit
statements. This next-stage source also offers a separately enabled paired
[management panel](MEMORY_MANAGEMENT.md) for the same manual operations. The
Actor reads an existing store only when its operator supplies all memory
arguments and separately authorizes transmission. It never extracts or saves
conversation facts automatically. See [the local memory workflow](LOCAL_MEMORY.md) for the
private scope file and the explicit recording confirmations.

The selected scope is fixed by local configuration before app startup. Browser
requests, generated text and remembered text cannot choose another user,
character, world, database, or provider. This prototype admits one local
operator and one active application session; it is not a multi-user service.

## Additional transmission consent

Local storage consent and developer raw-recording consent do not authorize
sending stored evidence to a model. The following additional flag authorizes
the selected scope's bounded evidence for this app invocation:

```bash
python tools/live_dev.py check \
  --env-file "$HOME/.config/mira/development.env" \
  --admission "$HOME/mira-runtime-admission.json" \
  --memory-db "$HOME/.local/share/mira-private/memory.sqlite3" \
  --memory-scope-config "$HOME/.local/share/mira-private/scopes.json" \
  --memory-scope local-mira \
  --authorize-memory-to-codex-and-jev \
  --create-local-operator-pairing
```

Use your actual private paths and scope alias. Both files must already exist
outside the checkout, have an owner-only private parent, and pass the path
checks. The database is never created by the application reader. `check`
validates the bounded scope configuration and declared paths, but does not open
the database or prove schema, credentials, model entitlement, or live readiness.

After reviewing the scope and recipients, use the same arguments with `serve`
instead of `check` to start the explicitly admitted local text app. Selected
stored evidence can go to Codex generation and TypeSafe JEV output review. Input
permission classification receives current reliable input and actual presented
history; memory text is excluded from that provider-visible decision payload.
Existing provider request/time limits continue to apply and are not dollar
caps. Nothing is sent by the no-argument command, `--help`, `check`, ordinary
mock startup, or the offline rehearsal.

This first application-recall entry is text-only. Combining it with a speech
factory is rejected: recalled information in generated speech would introduce
Google as another recipient, requiring a separately disclosed voice-memory
option. Existing voice mode without memory remains available through
`tools/live_voice.py`.

## Local operator pairing

Memory mode requires the additional `--create-local-operator-pairing` option.
`check` creates nothing. `serve`, after configuration and frontend build pass,
creates one new owner-only (0600) file in the existing private memory directory.
Only that file's location is printed. Enter its code in the local page's password
field within five minutes. It never appears in a URL, browser storage, or logs.
The one-use code authorizes only this running app; it is not an account login,
provider credential, or permission to write memory. Pairing uses an HttpOnly,
SameSite=Strict session cookie bound to the same browser origin and app instance.

Before pairing, private session creation, recall, media and diagnostics are
blocked and the database is not opened. Each session still needs its separate
session token. Stop cancels the current turn; it does not revoke operator access.
Use the explicit revoke control to close sessions/readers and invalidate access.
After revocation or app shutdown, restart with a new code to pair again. Old files
are not automatically deleted; their codes have no authority in a new launch.

This protects against another unauthenticated browser or local HTTP caller. It
does not protect against someone who can read the private code file, control the
paired browser, or run code as the same OS user. Do not expose this loopback
prototype to a shared network or treat it as multi-user identity authentication.
Local recording, provider-transmission consent, and operator pairing are three
separate controls; none inherits permission from another.

## Evidence and lifecycle rules

Each turn reads one bounded immutable packet from the fixed scope. Current
input is retained in full; a separate bounded lexical query selects optional
past evidence. Mandatory current facts and stored user-stated boundaries cannot
be silently truncated to fit. Exceeding a hard limit fails explicitly.

The same packet is bound to generation and output review. It contains source
labels and revisions, not authority. It cannot grant an action, change current
permissions, rewrite actual presentation history, disclose authored secrets,
or execute instructions embedded in remembered text. Current reliable input
and application-owned permissions/presentation facts retain precedence.

The Actor checks the store revision after awaited work and before issuing new
grants. A correction or soft-forget observed before that validation makes the
old candidate stale; there is no automatic model retry. This is optimistic
revision validation, not a transaction held across model calls. A later manual
database change does not retroactively undo already presented content or an
already issued grant. Stop and newer input remain the controls that revoke the
current output branch.

Reads run through a bounded read-only worker outside the Actor state lock.
Stop, newer input and Close must discard late results. The app owns and closes
the reader; deleting one session does not transfer that ownership. The Actor
reader never calls store mutation methods. Optional manual management uses a
separate explicitly authorized writer with revision and idempotency checks.

Raw model input/output recording is suppressed for memory-enabled turns rather
than inheriting prior dialogue-recording permission. Default diagnostics retain
only safe errors and timing facts. No memory database, raw packet or private
scope configuration is included in normal diagnostics exports or release
archives.

## Still incomplete

This is lexical evidence recall over manually confirmed statements. It does not
implement automatic memory extraction, semantic embeddings, summary/history
organization, learned personality or stance, durable Actor event replay,
multi-device synchronization, a versioned story/canon system, or full M06.
Synthetic tests can verify wiring and authority boundaries; they do not prove
that a live model interprets every memory correctly or follows every preference.

## Next-stage explicit editing

The optional management-panel candidate is described in [MEMORY_MANAGEMENT.md](MEMORY_MANAGEMENT.md). Local edits require a separate launch flag and per-operation confirmation; enabling recall alone does not authorize them. Use the matching release record, not this link, to establish acceptance.
