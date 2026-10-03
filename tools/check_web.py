"""Build into a fresh lane-owned directory; never overwrite another agent's dist."""
import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # ESM applies even when a caller selects an output directory outside the repository.
    (output / "package.json").write_text('{"type":"module"}\n')
    compiler = ROOT / "node_modules/typescript/bin/tsc"
    command = ["node", str(compiler)] if compiler.is_file() else [shutil.which("tsc") or "tsc"]
    subprocess.run([*command, "-p", "apps/web/tsconfig.json", "--outDir", str(output / "dist")],
                   cwd=ROOT, check=True)
    tests = sorted(str(p) for p in (ROOT / "tests/web").glob("*.test.mjs"))
    if not tests:
        raise SystemExit("No frontend tests found")
    subprocess.run(["node", "--test", *tests], cwd=ROOT, check=True,
                   env={**os.environ, "MIRA_TEST_WEB_DIST": str(output / "dist")})


if __name__ == "__main__":
    main()
