# Standalone local-only memory console

This is a narrow loopback launcher and page for manually managing an already
existing private local memory store. It reuses the reviewed operator-pairing
and memory-management contracts, but does not start MIRA's Actor, session,
model, audio, or provider runtime. Every automated test uses synthetic values
and local fakes only.

## Requirements

### M06LMC-001: inert launcher and explicit local consent

Given no command or `--help`, the launcher prints help without reading config,
opening a database, creating a pairing code, or starting a server. `check`
requires explicit local-memory access consent; it may validate only the named
external database/scope-file metadata and the selected scope document. It
never opens the database, starts a server, or creates pairing material. A
standalone local-management options type carries no provider-transmission
authorization field and does not call the recall/transmission loader.

### M06LMC-002: separate write and pairing opt-ins

Given `serve`, the operator must separately select local-memory access,
authorize local writes, and request `--create-local-operator-pairing`. Before
those explicit choices pass validation, serve does not create pairing material
or open the store. Pairing material is one-use, per-launch, ephemeral, written
with the existing reviewed private-file helper to the already-private database
directory, and its code is never logged or put in a URL. Test code never invokes
the production random-code generator.

### M06LMC-003: small allowlisted loopback surface

Given a running console, it binds only `127.0.0.1`, accepts only approved
loopback Host/Origin pairs, and exposes only health, the dedicated page and
its exact static resources, the existing operator pairing routes, and the
existing memory-management routes. The console has no session, Actor,
diagnostic, audio, provider, model, or application-config routes, and no
outbound network client or provider factory.

### M06LMC-004: lazy private-store access and bounded cleanup

Given a console before successful pairing, health/status/static requests and
unauthorized management requests do not open the private SQLite database. The
existing fixed-scope management factory is first invoked only after the
one-use pairing code is accepted. Revoke and application shutdown revoke the
pairing capability, close the manager/writer, and bound late factory/close
cleanup. The service never creates a missing database, changes user-path
permissions, or changes existing data outside confirmed management
operations.

### M06LMC-005: dedicated truthful static experience

Given the standalone page, it loads its installed HTML, CSS, and dedicated
JavaScript resource without MIRA's chat composer. It reuses
`mountOperatorPairing` and `mountMemoryManagement`. The page states that this
console has no provider route and does not transmit memory text; local pairing
and local write consent do not grant provider permission. Save, correct,
reversible tombstone, restore, per-operation confirmation, stale-revision
handling, unknown-write same-ID reconciliation, and retention disclosures
remain in force.

## Scenarios

- no command and `--help` are inert;
- `check` without local consent performs no scope validation;
- consented `check` validates an existing external private scope but does not
  open the database or create a pairing file;
- serve rejects missing local-write or pairing consent before any side effect;
- pair/status/static/health work without store access; an accepted code lazily
  opens one synthetic local store;
- wrong Host/Origin, missing session cookie, unsupported API, and non-loopback
  server binding are denied;
- revoke and shutdown close the manager once and invalidate the code/cookie;
- page bundling/resource checks prove only the dedicated entry is used.

## Verification limits

All tests use synthetic scope names and records, fake providers/transports
(none are constructed), and local temporary files. They do not use real user
data, a real browser, an account, a model, provider network traffic, or a
third-party service. A passing software suite does not prove a user's actual
browser/device experience.
