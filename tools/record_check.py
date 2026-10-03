"""Record local checks without replacing earlier evidence. Never run secrets through this tool."""
import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.quality_run import fingerprints as quality_fingerprints


def fingerprints() -> dict[str, str]:
    # One source boundary for directed receipts and aggregate quality runs.
    return quality_fingerprints(ROOT)


def git_head() -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True)
    parser.add_argument("--feature", default="fnd-02")
    parser.add_argument("--expect-exit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", args.id):
        parser.error("Use a path-safe, unique lowercase run id.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", args.feature):
        parser.error("Use a path-safe feature id.")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A command after -- is required.")
    folder = ROOT / "docs/verification" / args.feature / "runs" / args.id
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit("Evidence already exists. Choose a new run id; do not replace prior logs.") from None
    before = fingerprints()
    started_at = datetime.now(UTC).isoformat()
    start = time.monotonic()
    timeout = False
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=args.timeout)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        code, timeout = 124, True
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
        stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
    except OSError as error:
        code, stdout, stderr = 127, "", f"{type(error).__name__}: {error}\n"
    after = fingerprints()
    (folder / "stdout.txt").write_text(stdout, encoding="utf-8")
    (folder / "stderr.txt").write_text(stderr, encoding="utf-8")
    changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    report = {
        "run_id": args.id, "command": command, "cwd": ".", "python": sys.version,
        "platform": platform.platform(), "git_head": git_head(), "started_at": started_at,
        "ended_at": datetime.now(UTC).isoformat(), "duration_seconds": time.monotonic() - start,
        "exit_code": code, "expected_exit_code": args.expect_exit, "timed_out": timeout,
        "expectation_met": code == args.expect_exit and not timeout,
        "source_before": before, "source_after": after, "changed_during_run": changed,
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        "scope": "Local synthetic/test checks, not provider, device, or independent human validation",
    }
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(stdout, end="")
    print(stderr, end="", file=sys.stderr)
    print(f"Recorded {args.id}: exit={code}; expected={args.expect_exit}; changes={len(changed)}")
    raise SystemExit(0 if report["expectation_met"] else 1)


if __name__ == "__main__":
    main()
