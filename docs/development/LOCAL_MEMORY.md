# Explicit local memory workflow

This is a small, opt-in operator CLI over the typed SQLite memory store. It is
separate from MIRA's web app and generation path. The existing
`MemoryEventJournal` remains an in-session diagnostic journal; it is not durable
memory. This tool stores no real user information in its tests or examples.

The CLI does not call a model, provider, browser, or network service. It does
not read session transcripts, HTTP requests, or diagnostics. A saved entry is
an exact statement supplied and confirmed by a human operator. It does not
prove the statement independently, and it does not establish a presentation
receipt. This CLI itself performs no automatic recall, personality learning or
summary generation. A separately enabled text-application reader can consume
these manually saved statements; see [Actor memory admission](ACTOR_MEMORY.md).
The CLI's local-access consent does not authorize that provider transmission.

## Explicit private scope

Create a private server-owned scope file and keep it outside public source
control. The JSON shape is intentionally narrow; the CLI accepts a scope alias,
then resolves `user_id`, `character_id`, and `world_id` from that file. It does
not accept those IDs, a bank ID, or a scope chosen by model output as command
arguments or packet content.

Example shape (replace placeholders locally; do not use these as real IDs):

```json
{
  "version": 1,
  "scopes": [
    {
      "name": "local-mira",
      "user_id": "operator-assigned-user",
      "character_id": "mira",
      "world_id": "rainy-cafe"
    }
  ]
}
```

On POSIX systems, keep the scope file and its parent directory private to the
current user (for example, mode `0600` on the file and `0700` on a private
directory). The CLI rejects symlinked or group/world-accessible scope files.
The SQLite adapter similarly enforces owner-only storage and rejects unsafe
existing paths rather than changing their permissions. Always choose the
database path explicitly.
Both the database and scope-config file must be outside this repository checkout;
the CLI rejects lexical paths under the checkout and symlinks resolving into it.
This prevents private SQLite data or WAL/SHM sidecars from being captured with
source archives. The ordinary diagnostic export has no connection to this store
and contains no local memory records.

## Commands

Every store command requires `--db`, `--scope-config`, `--scope`, and
`--consent-local-memory`. That flag is an explicit opt-in to read or write the
selected local scope. No arguments prints help and does not open or create a
database. A write also displays the selected alias, source/kind and retention
behavior, then requires an explicit terminal confirmation before opening for a
write. Do not put statement text in command-line arguments; the CLI prompts for
it interactively instead.

```sh
python tools/memory.py

python tools/memory.py record \
  --db /private/mira-memory.sqlite3 \
  --scope-config /private/mira-memory-scopes.json \
  --scope local-mira --kind boundary --consent-local-memory

python tools/memory.py inspect \
  --db /private/mira-memory.sqlite3 \
  --scope-config /private/mira-memory-scopes.json \
  --scope local-mira --consent-local-memory

python tools/memory.py context \
  --db /private/mira-memory.sqlite3 \
  --scope-config /private/mira-memory-scopes.json \
  --scope local-mira --consent-local-memory

python tools/memory.py recall \
  --db /private/mira-memory.sqlite3 \
  --scope-config /private/mira-memory-scopes.json \
  --scope local-mira --consent-local-memory

python tools/memory.py correct \
  --db /private/mira-memory.sqlite3 \
  --scope-config /private/mira-memory-scopes.json \
  --scope local-mira --entry-id ENTRY_ID --consent-local-memory

python tools/memory.py forget \
  --db /private/mira-memory.sqlite3 \
  --scope-config /private/mira-memory-scopes.json \
  --scope local-mira --entry-id ENTRY_ID --consent-local-memory

python tools/memory.py restore \
  --db /private/mira-memory.sqlite3 \
  --scope-config /private/mira-memory-scopes.json \
  --scope local-mira --mutation-id FORGET_MUTATION_ID --consent-local-memory
```

`record` permits only `user_statement` provenance and requires the operator to
attest that the entered text is an explicit user statement, not an inference.
`--kind boundary|episodic` is selected by the operator; the CLI never guesses
from prose. A correction is a new user statement that supersedes one entry,
preserving the old row and the relationship. A boundary correction remains the
current boundary head. Each local entry gets a local source-event ID; it is not
a reference to a web session event.

The existing `PrivacyFilter` rejects recognized secret-shaped strings before
storage, without changing the text. This is a narrow second defense and not a
general secret detector or permission to store information without consent.

`forget` is reversible soft invalidation. It suppresses the target and
dependent records from recall, but the source text remains in the private
SQLite file and can be restored with the matching mutation ID. It is not secure
erasure, and the CLI has no purge command. The confirmation prompt states this
before writing. Keep backups under the same protection as the database.

Read text from stdin rather than command-line arguments: `recall` prompts for a
query, and `context` prompts for current request text, then optional boundary
and correction lines. This avoids putting private text in shell history or the
process list. Record and correction commands prompt for the exact statement too.

## Context packet preview

`context` freezes one deterministic JSON packet from the current request, any
operator-supplied current boundary/correction lines, the persisted current
boundary heads for this exact scope, and a bounded lexical recall. The packet
includes its monotonic per-scope snapshot revision; if evidence changes between
the required-fact read and optional recall, assembly fails closed instead of
retrying or mixing revisions. Explicit
caller facts come first. Persistent boundary heads and corrections come before
optional past candidates. A missing/late recall is empty; it cannot mutate an
already-returned packet. All mandatory lines are kept; if they do not fit the
packet budget, the command fails rather than silently dropping or truncating
them. Optional candidates are bounded by count, UTF-8 bytes, and a short local
SQLite query deadline.

Past recall is typed as untrusted quoted data. Source labels and source event
versions remain separate fields; no generated summary is created. Text in a
candidate is evidence content, never an instruction or permission. The same
untrusted-text label applies to persisted boundary statements; “mandatory” means
retained in the packet budget, not executable authority. Explicit caller facts
have higher factual precedence than stored history. Secret backstory,
interpretations, generated visualizations and unverified presentation receipts
are excluded from this prototype packet. This CLI's context output is a local preview. The separately admitted application
reader uses the same packet builder but has its own Actor/review version guards
and explicit provider-transmission consent; it never exports the database or
automatically records dialogue.
Current permissions, reliable new user input and already-presented history
remain the authorities in the product.

Global `inspect` is deliberately bounded to at most 1,000 history events. When
that history is partial, row statuses are `unknown_partial_history`; use
`--entry-id` to inspect a bounded correction lineage and its forget/restore
events. These statuses describe stored records only and do not turn them into
current permissions or confirmed presentation facts.

## Test scope and current limit

Automated tests use synthetic statements and temporary directories only. They
exercise explicit consent, scope isolation, source provenance, correction
supersession, reversible forget, restart persistence, query bounds, and packet
budget/deadline behavior. They do not establish model behavior, naturalness,
secret-disclosure safety, product integration, or user-device acceptance.

## Local page without provider setup

The separate [local-only management page](LOCAL_MEMORY_CONSOLE.md) uses the same explicitly selected private store and one-use pairing. It has no model or voice routes, needs no API keys, and gives no provider-transmission consent. Read the matching delivery record for its software acceptance.
