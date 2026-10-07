# DEV-RUNTIME-ADMISSION-01 verification

Recovery checkout: `424b3bf` plus the current source restoration in the recovered checkout. This report records only commands run on the restored source; it does not recreate historical receipts or claim the old worktree hashes.

## Focused synthetic checks

Command:

```text
python -m pytest tests/contracts/test_runtime_admission_preparation.py tests/contracts/test_codex_generation_process.py tests/contracts/test_codex_development_context.py -q
```

Result: **69 passed**. The setup and process contract tests use synthetic metadata transports and synthetic child processes. No native Codex executable, provider network call, inference, login, or credential-file read was performed.

The new traceability manifest independently validated all **3 requirements** against collected test node IDs.

## CLI behavior

`python tools/prepare_runtime_admission.py` printed `status=unarmed`, `metadata_probe=not_run`, and `admission_written=false`. `--help` describes the metadata traffic, separate policy/content flags, data recipients, billable JEV requests, per-invocation reset behavior, and the fact that request ceilings are not dollar caps.

## Checks not completed

The repository-wide `tools/check_specs.py` invocation stopped on a concurrent OBS-02 traceability mapping that names a JavaScript `.mjs` test, while the current collector only accepts Python `.py` test modules. The new runtime-admission manifest itself passes the independent check above.

`ruff` was unavailable in the prepared virtual environment (`No module named ruff`); no package was installed.

## 2026-10-04 platform-pin extension

The source now supports only the exact official Codex CLI 0.159.2 native pins for Linux x86_64, macOS arm64, and macOS x86_64. The prior Linux digest remains the `PINNED_EXECUTABLE_SHA256` compatibility alias. Unknown OS/architecture, cross-platform or arbitrary digests, platform drift, and missing or mismatched initialization platform fields fail closed. Platform metadata is derived from actual runtime `sys.platform` and `platform.machine()` facts, not from configuration/environment override.

The two exact Darwin release archives, published GitHub release SHA-256 values, locally verified native-member SHA-256 values, archive-member checks, and evidence limits are recorded in [Codex platform pin provenance](../../../docs/development/CODEX_PLATFORM_PIN_PROVENANCE.md). No binary was executed.

Recorded test runs on the restored source:

- `../../../docs/verification/dev-runtime-admission-01/runs/007-red-codex-platform-pins-final/`: the final 19-node platform contract file produced **16 failures / 3 passes** against the prior Linux-only pin implementation; this is the directed RED.
- `../../../docs/verification/dev-runtime-admission-01/runs/008-green-codex-platform-pins-final/`: the same contract file produced **19 passed**.
- `../../../docs/verification/dev-runtime-admission-01/runs/009-green-codex-platform-regression-final/`: platform pins plus runtime preparation, generation process, generation, read-only installation, and development-context contracts produced **150 passed**.

The broader providers lane was also attempted with `.venv/bin/python tools/check.py --lane providers --jobs 3`. It completed with **1,207 passed / 1 failed / 1,208 total**; the unrelated failure is `test_clean_no_dist_copy_builds_and_serves_compiled_main_js`, whose copied web checkout has no `node_modules/typescript/bin/tsc` or `node_modules/esbuild/lib/main.js`. The lane is therefore not reported green. A first attempt invoked the system interpreter without pytest and is retained separately; no packages were installed for either attempt. The targeted feature traceability check passed all three mapped requirements.

These are synthetic/offline software checks. The user Mac native startup, platform handshake against an installed CLI, login, inference, and device acceptance are **not run**. The previously frozen 09:52 package remains Linux-only; this extension belongs only in a complete matching later source/package.
