# Local-only memory page

This optional entry manages existing local records without Codex, JEV, Google,
provider credentials, or a model connection. It is a separate page with no chat,
model, microphone, audio, or generation routes. It does not automatically record
conversations. The first source entrypoint import failure was reproduced with a
sanitized `python -I` subprocess and fixed; complete release/independent results
belong to the matching delivery record.

## Prepare once

Use the ordinary project-local Python and Node dependency bootstrap in
[QUICKSTART](QUICKSTART.md). No API keys are needed for this page. Create your
private database and scope configuration using the explicit
[local memory CLI](LOCAL_MEMORY.md). They must already exist outside the checkout;
this page does not create a database or change existing permissions.

Select your own paths, then validate the scope metadata:

```sh
.venv/bin/python tools/local_memory.py check \
  --db "$HOME/.local/share/mira-private/memory.sqlite3" \
  --scope-config "$HOME/.local/share/mira-private/scopes.json" \
  --scope local-mira --consent-local-memory
```

`check` does not open SQLite, prove its schema, create a pairing code, start a
server, or contact a provider. No arguments or `--help` is inert.

## Open the page

```sh
.venv/bin/python tools/local_memory.py serve \
  --db "$HOME/.local/share/mira-private/memory.sqlite3" \
  --scope-config "$HOME/.local/share/mira-private/scopes.json" \
  --scope local-mira --consent-local-memory \
  --authorize-local-memory-writes --create-local-operator-pairing
```

The launcher builds the local page from already installed locked dependencies,
then listens at `http://127.0.0.1:8761`. It prints the location of a new private,
one-use pairing file, not its code. Read that file yourself and enter the code in
the page. Do not put it in a URL, chat, screenshot or public repository. A custom
loopback port can be selected with `--port`.

After pairing, expand the records panel. Saving, correcting, reversible
forgetting, and restoring require local-write consent and a separate confirmation.
Forget removes a record from recall but retains its text in local history; it is
not secure erasure. A lost response is not success or rollback. Explicit
reconciliation repeats the exact operation ID/body only with current consent.

Revoke clears private page state and invalidates this launch's pairing. Stop the
local server to finish. Old pairing files are not automatically deleted, but
cannot authorize a different launch. The page protects against unpaired callers;
it cannot protect against malware running as your OS user or a compromised paired
browser. It must not be exposed directly to a shared network.

## Separate from model recall

This page grants no provider-transmission permission. Opening it does not send
records to anyone. If you separately enable the text app's memory recall later,
its selected records may be sent to Codex and TypeSafe/JEV only under that app's
separate disclosure/authorization. See [ACTOR_MEMORY](ACTOR_MEMORY.md).

Automated checks use synthetic SQLite, ASGI, fake browser objects and installed
static resources. They do not establish actual Mac/browser rendering or live
model memory quality. Full M06 learning, automatic extraction and synchronization
remain outside this slice.
