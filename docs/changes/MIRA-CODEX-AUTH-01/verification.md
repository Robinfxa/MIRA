# MIRA-CODEX-AUTH-01 verification

Run ID: `20261004-2155Z-auth-01`

This report is bound to the synthetic-only auth slice in this work tree; it does
not certify the sibling direct Responses adapter, final factory wiring, account
eligibility, a real OAuth grant, provider terms, or live model access.

## Executed

- `PYTHONPATH=apps/api/src <trusted-python> -m pytest -p no:cacheprovider --basetemp=/tmp/mira-subscription-auth-001/final tests/contracts/test_codex_subscription_auth.py -q` — **14 passed**. All requests used `httpx.MockTransport`; temporary stores contained synthetic test tokens only.
- `PYTHONPATH=apps/api/src <trusted-python> -m pytest -p no:cacheprovider --basetemp=/tmp/mira-subscription-auth-001/architecture tests/architecture/test_boundaries.py -q` — **7 passed**.
- `PYTHONPATH=apps/api/src <trusted-python> tools/check_specs.py` — **254 requirement links to collected test node IDs**; this is collection/link verification, not test execution.
- `PYTHONPATH=apps/api/src <trusted-python> tools/provider_login.py --help` — usage rendered; parser exits before store creation or OAuth.
- `python -m compileall` ran earlier during implementation; subsequent final Python edits are covered by the final pytest collection/execution above.

`<trusted-python>` was the pre-existing `/workspace/shared/mira-combined-runtime-0947/.venv/bin/python`, which already had pytest, HTTPX 0.28.1, and Pydantic 2.13.4. No packages were installed or changed. Test temporary storage and output were outside this work tree.

## Not run / limits

- No real device-code request, browser opening, account/token request, subscription/model request, or API-key fallback.
- No full/affected quality run, package build, Windows/macOS execution, or live browser flow.
- Windows profile ACL inheritance and end-user behavior are not independently verified.
- `ruff` was unavailable in the trusted environment.
- No user credential store was read or changed.

## Incremental metadata/CLI and assembled verification

Run ID: `20261004-2212Z-auth-integration`

- Auth tests after adding optional JWT metadata extraction, CLI `--auth-store`, and error-code allowlisting: **15 passed**.
- Assembled direct Responses + app composition + live provider launcher + auth + architecture-boundary suite: **62 passed**. The auth async tests use pytest's event-loop fixture rather than calling `asyncio.run`, so they don't replace the shared loop policy.
- `tools/check_specs.py`: **262 requirement links** resolve to collected tests; this is link verification only, not execution evidence.
- All auth/refresh/OAuth network steps remained synthetic `httpx.MockTransport`; no real OAuth, model, or account request was made.
- Combined test output was kept in the integration evidence workspace for this run. The new synthetic temp fixtures were not removed after the run.

## Final read-only status/path-guard recheck

Run ID: `20261004-2216Z-auth-final`

- The first status-side-effect recheck found that a checkout path was no longer rejected by `status()` after removing its lock-file write. The path guard was moved to the shared read boundary; the prior failed run is preserved in `assembled-authfix-2215.log`.
- Re-ran direct Responses, direct app composition, live provider launcher, auth, and architecture-boundary tests together: **71 passed in 2.16s**. No `ResourceWarning` or loop-leak warning occurred.
- Auth claims, expired/rotated refresh, CLI error allowlisting, explicit auth-store override, no-write status, logout/refresh ordering, and checkout-path refusal remain covered by synthetic fixtures.
- Output retained at `assembled-authfix-2216.log`; synthetic test basetemp retained at `authfix-2216-basetemp`. No cleanup was performed after the run.
