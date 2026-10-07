# DEV Node preflight verification

Date: 2026-10-04 UTC

`tools/dev.py` now distinguishes a missing Node.js/npm prerequisite from missing TypeScript/esbuild project packages. Missing Node/npm explains that Node.js 22.12+ with npm must be installed before `tools/bootstrap.py`; a ready Node/npm toolchain with project build packages missing is directed to the explicit bootstrap. The launcher then runs the fixed `npm run build` only after the contract check and does not start the server after a build failure. Launcher errors still exit 2; startup does not install packages, load dotenv, or add provider credentials.

TDD evidence:

- RED, baseline commit `424b3bfbb4a9b21db9ffe15bf025cdbddfd10650`: the three new prerequisite/build-order/failure tests failed against the original launcher. Output and snapshot hashes: `runs/001-red/`.
- GREEN, `runs/002-green/`: `python -m pytest tests/unit/test_dev_startup.py -q` passed, 19 tests. Existing invalid Python, invalid profile/port controls, and missing-TypeScript failure behavior remain covered. Missing Node/npm cases use real `shutil.which` with a synthetic controlled PATH; subprocesses are stubbed, so they do not install or run tools.

The repository's current `node_modules` provides TypeScript but not esbuild; this focused verification therefore did not run an actual `npm run build`. Bundled build integration is left to the renderer/integration owner.
