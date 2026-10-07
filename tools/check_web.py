"""Build in an external disposable directory; keep lane logs/artifacts in the requested output dir."""
import argparse
from contextlib import contextmanager
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _paths_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left.is_relative_to(right) or right.is_relative_to(left)


@contextmanager
def _external_build_root(project_root: Path):
    project = project_root.resolve()
    candidates = [Path("/tmp"), Path(tempfile.gettempdir()), project.parent]
    seen = set()
    for candidate in candidates:
        try:
            parent = candidate.resolve(strict=True)
        except OSError:
            continue
        if parent in seen or not parent.is_dir():
            continue
        seen.add(parent)
        try:
            temporary = tempfile.TemporaryDirectory(prefix="mira-web-check-", dir=parent)
        except OSError:
            continue
        build_root = Path(temporary.name).resolve()
        if _paths_overlap(build_root / "dist", project):
            temporary.cleanup()
            continue
        try:
            yield build_root
        finally:
            temporary.cleanup()
        return
    raise RuntimeError("Cannot create a fresh web build directory outside the project root")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Preserve the lane artifact directory while keeping its disposable bundle external.
    (output / "package.json").write_text('{"type":"module"}\n')
    node = shutil.which("node")
    if node is None:
        raise SystemExit("Missing Node.js; run bootstrap with Node.js 22.12+ installed")
    tests = sorted(str(p) for p in (ROOT / "tests/web").glob("*.test.mjs"))
    if not tests:
        raise SystemExit("No frontend tests found")
    with _external_build_root(ROOT) as build_root:
        dist = build_root / "dist"
        (build_root / "package.json").write_text('{"type":"module"}\n')
        subprocess.run([node, "tools/build_web.mjs", "--outdir", str(dist)],
                       cwd=ROOT, check=True)
        subprocess.run([node, "--test", *tests], cwd=ROOT, check=True,
                       env={**os.environ, "MIRA_TEST_WEB_DIST": str(dist)})


if __name__ == "__main__":
    main()
