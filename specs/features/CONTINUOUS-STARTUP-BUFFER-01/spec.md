# Continuous listening bounded startup buffering

Base: current integration snapshot copied from mira-firstperson-integration-20261005T0613Z
at 2026-10-05 06:52 UTC. The worker changes only the application listening buffer,
its contract tests and this specification. No schema, Actor or frontend changes.
The existing providers contract-test glob is the unique test owner; continuous,
HTTP and Google STT adapters are consumers. Use explicit --files affected checks
because this source snapshot has no Git metadata. All frames and SDK responses are
synthetic, with injected fake RPC clients and no network or credentials.

### CONTINUOUSSTARTUPBUFFER-001 Preserve paced audio through startup

Given 20ms PCM frames and a Google streaming RPC held for one second before
consumption, when it starts consuming, then every accepted frame, including silence,
reaches the RPC in order. There is one RPC and no retry or automatic new lease.

### CONTINUOUSSTARTUPBUFFER-002 Enforce independent finite queue bounds

Given stalled consumption, when pending audio reaches 32,000 samples (64,000 bytes)
or 200 packets, then the next exceeding frame fails without advancing sequence or
sample counters. Consumption returns exactly the removed frame's capacity. Explicit
smaller packet limits remain effective. Large frames cannot bypass the PCM bound.

### CONTINUOUSSTARTUPBUFFER-003 Preserve finish, cancellation and lease limits

Given a full buffer, Finish drains all accepted frames without waiting for capacity;
Cancel immediately clears queued PCM and accounting and prohibits future pushes.
Existing finite lease duration, sample, count and pacing limits remain unchanged.
Offline tests do not establish real microphone, Google availability or user hearing.
