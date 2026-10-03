"""Install only declared development dependencies into .venv and node_modules.

Does not load .env, read credentials, initialize a provider, or install global packages.
A connected package registry is needed for a fresh install.
"""
import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-only", action="store_true")
    args = parser.parse_args()
    environment = ROOT / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(environment)
    subprocess.run([str(python), "-m", "pip", "install", "-r", "requirements/dev.lock"],
                   cwd=ROOT, check=True)
    if not args.python_only:
        npm = shutil.which("npm")
        if npm is None:
            raise SystemExit("Install Node.js 22 and npm before running bootstrap.")
        subprocess.run([npm, "ci", "--ignore-scripts"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
