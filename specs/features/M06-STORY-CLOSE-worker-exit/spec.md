# M06 story checkpoint worker exit

### M06CLOSE-001 Actual thread completion
Given an explicitly authorized synthetic checkpoint worker, when its completion Future becomes ready before the operating-system thread returns, aclose must still await actual thread exit without blocking the event loop. It continues rejecting new work throughout closing. The same existing finite close deadline covers both operation drain and thread exit; timeout does not claim completion. A later close can reconcile actual exit. Never-opened and repeated close remain inert.

Owner: providers through tests/contracts/test_*.py. Baseline: frozen 20261005-2242 source. Consumers: persistent character binding, session replacement, operator revocation. No new dependency, provider call, private user state or permission. The existing full-suite failure exposed this race; targeted synthetic thread-tail barriers establish it deterministically. Verification artifacts are retained outside the delivered source.
