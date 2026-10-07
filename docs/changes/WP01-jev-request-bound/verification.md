# WP01 JEV output-review request bound

The output-review adapter's local serialized request envelope is 32 KiB. The full
context, candidate, response contract, snapshot, input observation, questions, and
binding digests remain in each review request. The independent input-review adapter
retains its existing 16 KiB envelope. No question, semantic threshold, request budget,
response byte ceiling, retry policy, provider token or provider cost limit changed.

## RED and GREEN

The existing frozen cross-module RED was first run against the current 16 KiB project
checkout with the same synthetic ASGI composition used by the independent audit. Its
second three-effect turn reached the output seal at 16,677 bytes, failed with
`jev_request_too_large`, and retained one output-review request slot. All four input
reviews had completed and the first three output reviews were ALLOW. Capture:
`private audit receipt: 20261004T0232Z/two_turn_red.log`.

After raising only the output-review cap, the identical audit test passed against the
same composed app and synthetic providers. Capture:
`private audit receipt: 20261004T0232Z/two_turn_green.log`.

## Executed checks

- New backend/HTTP boundary and four-round ASGI contracts: 4 passed.
- JEV review, HTTP transport, input, transport diagnostics, and the new contracts: 180 passed.
- Four actual ASGI text turns used 8 input-review calls, 8 output-review calls, and 4 fake Codex generations; complete presented history, contracts, observations and digests remained bound. Each output request fit within 32,768 bytes.
- Output backend admitted an exact 32,768-byte UTF-8 payload containing multibyte text and rejected 32,769 bytes as `jev_request_too_large` before transport. The HTTP transport accepted 32,768 bytes and rejected 32,769 before issuing a request.
- `tools/check_specs.py`: 162 requirement-to-test links collected. `git diff --check`: passed.

This is offline software/ASGI evidence using in-process synthetic transports only. It does
not establish a real provider request, account authorization or spend, browser/UI
presentation, human understanding, microphone use, or physical audio behavior.
