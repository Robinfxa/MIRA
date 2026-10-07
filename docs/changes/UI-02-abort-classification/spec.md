# UI-02: classify transport aborts without hiding failures

Baseline: immutable 0550 capture, also reproduce against compiled responsive UI. Owner: web lane (tests/web/*.test.mjs). No provider, browser, credential, public protocol or backend changes.

Given the app's own five-second request deadline, native default AbortError at fetch or body read must surface a fixed localized timeout reason. Given an unexpected AbortError while no owned signal was canceled, surface a distinct unexpected-interruption error. Given Stop, Close or newer input canceled the owner, suppress stale error/results through existing generation/ownership fences. Do not blanket-ignore errors named AbortError.

An uncooperative late response after a canceled/deadline request must not become new authoritative state. A late successful session creation must still receive bounded cleanup. Malformed JSON and ordinary network/server errors keep their real categories. Input timeout cannot claim the server rejected or did not receive the input, and must not auto-retry.

Use real AbortController/default DOMException, deterministic timer control, delayed fetch/body results, and actual controller generation transitions. Preserve frozen source and the chunk owner's independent FIFO edits.
