"""Run a narrowly scoped local-only console for manually managed memory."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Direct checkout launch must not depend on pytest, PYTHONPATH, or an installed MIRA wheel.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/api/src"))
DEFAULT_PORT = 8761
_BUILD_ENV_ALLOWLIST = (
    "PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "SystemRoot", "WINDIR",
)


class LocalMemoryEntryError(ValueError):
    """Safe launcher failure with no private path or content."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command")
    for name in ("check", "serve"):
        command = subcommands.add_parser(name)
        command.add_argument("--db", type=Path, required=True,
                             help="existing private SQLite file outside this checkout")
        command.add_argument("--scope-config", type=Path, required=True,
                             help="private operator-owned scope JSON outside this checkout")
        command.add_argument("--scope", required=True, help="scope alias selected from the private file")
        command.add_argument("--consent-local-memory", action="store_true",
                             help="allow this command to validate/use the selected local scope")
        if name == "serve":
            command.add_argument("--authorize-local-memory-writes", action="store_true",
                                 help="separate consent for confirmed local edits")
            command.add_argument("--create-local-operator-pairing", action="store_true",
                                 help="create one-use local pairing material for this launch")
            command.add_argument("--port", type=int, default=DEFAULT_PORT,
                                 help=f"loopback port (default {DEFAULT_PORT})")
    return parser


def _load_options(args):
    from mira.config.local_memory import load_local_memory_management_options

    return load_local_memory_management_options(
        database=args.db,
        scope_config=args.scope_config,
        scope_alias=args.scope,
        consent_local_memory=True,
        checkout_root=ROOT,
    )


def _child_environment() -> dict[str, str]:
    # Do not enumerate the process environment: read only ordinary runtime
    # variables needed to find Node and its temporary directory. API keys,
    # MIRA config, and Python overrides are never inspected or inherited.
    return {key: os.environ[key] for key in _BUILD_ENV_ALLOWLIST if key in os.environ}


def _prepare_frontend() -> None:
    node = shutil.which("node")
    compiler = ROOT / "node_modules/typescript/bin/tsc"
    bundler = ROOT / "node_modules/esbuild/lib/main.js"
    if node is None:
        raise LocalMemoryEntryError("Serve requires Node.js and the already installed locked browser dependencies.")
    if not compiler.is_file() or not bundler.is_file():
        raise LocalMemoryEntryError("Serve requires the locked TypeScript/esbuild dependencies; no packages were installed.")
    try:
        subprocess.run([node, str(ROOT / "tools/build_web.mjs")], cwd=ROOT,
                       env=_child_environment(), check=True, timeout=90,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise LocalMemoryEntryError("The dedicated local page could not be prepared; the server was not started.") from None


def _create_pairing_material(directory: Path):
    from tools.operator_pairing_file import create_pairing_material

    return create_pairing_material(directory, checkout_root=ROOT)


def _run_server(app, *, port: int) -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, workers=1, access_log=False,
                server_header=False, date_header=False, log_config=None)


def _run_check(args) -> int:
    if args.consent_local_memory is not True:
        raise LocalMemoryEntryError("check requires explicit --consent-local-memory; no private scope was read.")
    _load_options(args)
    print("Selected local scope metadata is valid. Database contents were not opened; no pairing or server was created.")
    return 0


def _run_serve(args) -> int:
    if args.consent_local_memory is not True:
        raise LocalMemoryEntryError("serve requires explicit --consent-local-memory.")
    if args.authorize_local_memory_writes is not True:
        raise LocalMemoryEntryError("serve requires separate --authorize-local-memory-writes consent.")
    if args.create_local_operator_pairing is not True:
        raise LocalMemoryEntryError("serve requires --create-local-operator-pairing.")
    if type(args.port) is not int or not 1024 <= args.port <= 65_535:
        raise LocalMemoryEntryError("port must be between 1024 and 65535.")
    options = _load_options(args)
    _prepare_frontend()

    from mira.bootstrap.local_memory_management import create_local_memory_management_factory
    from mira.entrypoints.http.local_memory_app import create_local_memory_app
    from mira.entrypoints.http.operator_pairing import OperatorPairing

    factory = create_local_memory_management_factory(options, authorized_local_writes=True)
    origin = f"http://127.0.0.1:{args.port}"
    local_origin = f"http://localhost:{args.port}"
    try:
        material = _create_pairing_material(options.database.parent)
        pairing = OperatorPairing(material.code, (origin, local_origin))
        app = create_local_memory_app(management_factory=factory, pairing=pairing,
                                      web_root=ROOT / "apps/web")
    except Exception:
        raise LocalMemoryEntryError("Local pairing or console setup failed; no database was opened.") from None
    print("Local memory console: " + origin, flush=True)
    print("Open the private one-use pairing file and enter its code in the page: "
          + str(material.path), flush=True)
    print("This launch exposes only local health/static, pairing, and fixed-scope memory-management routes. "
          "No provider transmission is enabled.", flush=True)
    _run_server(app, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as result:
        return int(result.code or 0)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "check":
            return _run_check(args)
        return _run_serve(args)
    except LocalMemoryEntryError as error:
        # Only this module's fixed messages are safe to surface; arbitrary OS/config
        # errors can contain private paths or input and remain suppressed below.
        print(str(error), file=sys.stderr)
        return 2
    except ImportError:
        print("Local memory dependencies are unavailable. Follow the documented project bootstrap first.", file=sys.stderr)
        return 2
    except (ValueError, OSError):
        print("Local memory setup failed; no private values were displayed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
