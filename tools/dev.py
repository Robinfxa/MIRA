"""Build and serve an explicitly offline mock/replay/rehearsal workbench. Never installs packages."""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_HELP = "Install explicitly with python tools/bootstrap.py, or select a ready --python PATH."


class StartupError(ValueError):
    pass


def child_environment() -> dict[str, str]:
    """Do not forward application settings or common provider credential variables.

    This is configuration isolation, not a filesystem or network sandbox. No
    live factory, SDK credential discovery, or dotenv loading is used by demo.
    """
    return {key: value for key, value in os.environ.items()
            if not key.startswith("MIRA_") and key not in {
                "PYTHONPATH", "PYTHONHOME", "OPENAI_API_KEY", "TYPESAFE_API_KEY",
                "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT",
                "GOOGLE_CLOUD_QUOTA_PROJECT", "CODEX_ACCESS_TOKEN", "ACCESS_TOKEN",
                "AZURE_OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            }}


def python_ready(python: str) -> bool:
    # Test actual imports, rather than a venv file's existence or find_spec on a
    # different interpreter. -I rejects incidental checkout/user PYTHONPATH.
    code = """import sys
if not (3, 11) <= sys.version_info[:2] < (3, 14):
    raise SystemExit(2)
sys.path.insert(0, sys.argv[1])
import uvicorn
from mira.config.loader import load_settings
from mira.entrypoints.http.app import create_app
"""
    try:
        result = subprocess.run([python, "-I", "-c", code, str(ROOT / "apps/api/src")],
                                cwd=ROOT, env=child_environment(), capture_output=True,
                                text=True, timeout=15)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def select_python(explicit: str | None) -> str:
    if explicit:
        if python_ready(explicit):
            return explicit
        raise StartupError("Selected Python is not usable (requires Python 3.11–3.13 and runtime dependencies). "
                           + INSTALL_HELP)
    environment = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    candidates = ([str(environment)] if environment.is_file() else []) + [sys.executable]
    for python in dict.fromkeys(candidates):
        if python_ready(python):
            return python
    raise StartupError("Missing compatible Python/runtime dependencies. " + INSTALL_HELP)


def web_build_command() -> list[str]:
    node = shutil.which("node")
    if node is None:
        raise StartupError(
            "Node.js 22.12+ and npm must be installed before project setup; bootstrap does not install Node. "
            "Install Node.js with npm, then run python tools/bootstrap.py for project dependencies."
        )
    compiler = ROOT / "node_modules/typescript/bin/tsc"
    esbuild = ROOT / "node_modules/esbuild/lib/main.js"
    try:
        result = subprocess.run([node, "--version"], capture_output=True, text=True,
                                timeout=10, env=child_environment())
    except (OSError, subprocess.TimeoutExpired):
        raise StartupError("Cannot run Node.js (requires 22.12+).") from None
    version = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", result.stdout)
    if result.returncode or version is None or tuple(map(int, version.groups())) < (22, 12, 0):
        raise StartupError("Node.js 22.12+ is required; no tools were installed.")
    if not compiler.is_file() or not esbuild.is_file():
        raise StartupError(
            "Missing declared TypeScript/esbuild build dependencies. "
            "Install project dependencies explicitly with python tools/bootstrap.py."
        )
    # Building uses only the locked local compiler/bundler. Starting npm for
    # this script may also start npm's update-notifier, which is unnecessary IO.
    return [node, str(ROOT / "tools/build_web.mjs")]


def demo_settings(*, root: Path, profile: str, port: int, scenario: str):
    from mira.config.loader import load_settings

    return load_settings(root=root, environ={"MIRA_PROFILE": profile}, overrides={
        "http": {"host": "127.0.0.1", "port": port,
                 "allowed_origins": [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]},
        "providers": {"generation": profile, "review": "fixture", "replay_scenario": scenario,
                      "allow_external_calls": False, "allow_paid_api": False, "api_key": None},
        "diagnostics": {"development_recording": False, "recording_consent": False},
    })


def serve(*, profile: str, port: int, scenario: str, character_renderer: str='static-pixi') -> None:
    # Explicit settings preserve the application's single loader/composition root.
    # Do not invoke python -m mira here: that is the configuration-aware entrypoint.
    sys.path.insert(0, str(ROOT / "apps/api/src"))
    import uvicorn

    from mira.entrypoints.http.app import create_app

    settings = demo_settings(root=ROOT, profile=profile, port=port, scenario=scenario)
    uvicorn.run(create_app(settings, web_root=ROOT / "apps/web",
                          **({'character_renderer':character_renderer} if character_renderer!='static-pixi' else {})),
                host=settings.http.host, port=settings.http.port, workers=1,
                access_log=False, ws_max_size=32768, ws_max_queue=8)


def demo_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be an integer between 1024 and 65535") from None
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1024 and 65535")
    return port


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", help="explicit ready Python interpreter; no fallback if invalid")
    parser.add_argument("--profile", choices=("mock", "replay", "rehearsal"), default="mock")
    parser.add_argument("--replay-scenario", choices=("photo-tour", "delayed-photo", "failed-tail"),
                        default="photo-tour")
    parser.add_argument("--port", type=demo_port, default=8000)
    parser.add_argument('--character-renderer',choices=('static-pixi','code-native-review'),default='code-native-review')
    parser.add_argument("--no-bootstrap", action="store_true",
                        help="compatibility option; startup never installs dependencies")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.serve:
            serve(profile=args.profile, port=args.port, scenario=args.replay_scenario,
                  **({'character_renderer':args.character_renderer} if args.character_renderer!='static-pixi' else {}))
            return 0
        python = select_python(args.python)
        build = web_build_command()
        env = child_environment()
        subprocess.run([python, str(ROOT / "tools/export_contracts.py"), "--check"],
                       cwd=ROOT, env=env, check=True, timeout=45)
        subprocess.run(build, cwd=ROOT, env=env, check=True, timeout=90)
        print(f"MIRA offline {args.profile} demo: starting http://127.0.0.1:{args.port}; "
              "no dotenv, service credentials, or live providers loaded.", flush=True)
        subprocess.run([python, str(ROOT / "tools/dev.py"), "--serve", "--profile", args.profile,
                        "--port", str(args.port), "--replay-scenario", args.replay_scenario,
                        '--character-renderer',args.character_renderer],
                       cwd=ROOT, env=env, check=True)
        return 0
    except KeyboardInterrupt:
        return 0
    except StartupError as error:
        print(f"Startup error: {error}", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired:
        print("Startup check timed out; no tools were installed.", file=sys.stderr)
        return 2
    except (OSError, subprocess.CalledProcessError):
        print("Startup command failed; check the preceding contract/build/server error.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
