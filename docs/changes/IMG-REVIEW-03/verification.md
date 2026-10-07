# IMG-REVIEW-03 offline compatibility evidence

Frozen base: `355609fe43149a902eb1e5ace53a1e3879826a1d` (2026-10-06).
All execution is cloud-local with generated pixels, fake opaque credentials and
injected HTTP transports. No live inference, credential/environment/private
database reads or user-computer operations were performed.

## Finding and limit

The subscription pixel reviewer reused the repaired direct Responses assembler
but retained `max_events=128`. An identical 470-byte, correctly bound JSON review
passed at 128 total SSE events and failed at 129. The production test fixture at
129 events is 21,735 decoded/wire bytes; at 258 events it is 41,730 bytes. Both are
below the unchanged 65,536-byte ceiling. The fixture includes matching completed
message and terminal snapshot. Only event partitioning changes the result.

The fix aligns the reviewer with the existing direct transport's bounded 1024
events. Byte ceilings (wire/decoded 65,536, line 16,384, output 8192), deadlines,
single request, pixel review and strict application binding/schema are unchanged.
The shared transport adds fixed reason classes for event/wire/decoded/line
overflows; the reviewer and component CLI expose corresponding fixed local codes
and the already-existing output-limit class. No provider text reaches errors.
The separate diagnostic owner carries these codes through job-bound diagnostics.

## Actual runs

- Frozen baseline: subscription review and output dimensions, 127 passed.
- Same directed 185-case set: RED 17 failed / 168 passed (19.00s); after the
  minimal implementation, GREEN 185 passed (18.62s). This is a real behavior RED,
  not a collection failure.
- Additional normal chat/native tool SSE, structured output, header, missing
  MIME, terminal and generation diagnostic regression: 161 passed (2.06s).
- Exact event boundary: 1024 events / 36,290 bytes accepted; 1025 events / 36,324
  bytes rejected as `subscription_review_event_limit`.
- High-partition wrong request identity, PNG digest, extra fields and missing
  checks remain rejected. Unknown metadata, over-wire, over-decoded, over-line and
  over-output fixtures retain distinct failures. Existing cancellation, PNG
  binding and strict JSON cases are included in the directed run.

The handoff's external `004-affected/report.json` is authoritative for the
affected lanes; this source record does not pre-claim its result. Raw RED/GREEN
logs and the exact event/wire/compressed-byte matrix accompany the handoff.

## Audit scope

Review model defaults to the explicit dialogue model unless separately selected;
account/model image entitlement remains unverified. Request content consists of
the bounded fictional specification, dimensions, required checks, requested
schema and exact canonical PNG data URL. Application request identity (normally
a UUID), specification digest, PNG digest and policy are checked exactly; private
session, parent, admission and resource IDs are absent from the request.

The existing subscription assembler already handles resolved model names,
omitted MIME on the fixed endpoint, compressed SSE, empty terminal snapshots,
split final messages and commentary. Successful output still requires completed
message events and a terminal, then one strict application JSON document. There
is no markdown extraction, arbitrary JSON recovery or review bypass.

Primary shape references read on 2026-10-06:
[Responses streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events)
describes text deltas as strings, without a fixed partition size;
[Images and vision](https://developers.openai.com/api/docs/guides/images-vision)
documents PNG/base64 image input and omitted detail defaulting to auto. These
public docs support shape checks, not private subscription-route guarantees.

The 2012 live log establishes generation returned, pixel review started and
review failed. Its exact reason was lost by a separate reply-epoch diagnostic
projection bug. This reproduced defect is not proof of that live failure's cause.
