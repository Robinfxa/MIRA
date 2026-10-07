# DEV-NATIVE-LAUNCH-01 verification

Scope: managed native launch flag and exact managed-home binding only. No production file outside `codex_support/process.py` changed for this slice. No native process, browser, auth file, or provider was accessed by these checks.

## RED / GREEN

- Initial direct RED command: `PYTHONPATH=apps/api/src .venv/bin/python -m pytest tests/contracts/test_codex_development_context.py -q -k 'managed_home or development_argv_preserves'`. Before implementation it reported 3 failed and 4 passed, exercising absent-home fallback, the missing launch flag, and bad `HOME` rejection.
- Final recorded GREEN: `docs/verification/dev-native-launch-01/runs/green-20261004t0344z/report.json`; 59 passed across all approved-development-context contract tests and the existing public argv contract.
- Spec link check: `.venv/bin/python tools/check_specs.py` reported 169 requirements linked to collected tests. This is collection/link evidence, not test execution evidence.
- `git diff --check` passed for the scoped files.

The production-source SHA-256 at this verification point is `e9b5ad17d1c1497c537110f65e71a904dfafe45932c31317b77b129f09cb325c` (`apps/api/src/mira/adapters/generation/codex_support/process.py`).
