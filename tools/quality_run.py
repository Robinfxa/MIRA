"""Small subprocess runner: isolated artifacts, bounded concurrency, scoped evidence.

No distributed worker pool, result cache, retry policy or cloud service is added.
"""
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from tools.quality_plan import Lane, Plan, PlanError, lane_files


def fingerprints(root: Path) -> dict[str, str]:
    result = {}
    for directory in ("apps/api/src", "apps/web/src", "apps/web/public", "tests", "tools", "config", "specs",
                      "requirements", "packages/contracts", "scripts", ".github"):
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("pyproject.toml", "setup.py", "package.json", "package-lock.json",
                 "apps/web/index.html", "apps/web/tsconfig.json", ".env.example", ".env.development.example"):
        path = root / name
        if path.is_file():
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _stop(process: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()  # Windows child-tree cleanup is not yet a verified capability.
    process.wait()


def _test_counts(folder: Path) -> dict | None:
    path = folder / "junit.xml"
    if not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
        suites = list(root.iter("testsuite"))
        return {name: sum(int(s.attrib.get(name, 0)) for s in suites)
                for name in ("tests", "failures", "errors", "skipped")}
    except (ET.ParseError, ValueError, OSError):
        return None


def _execute(root: Path, lane: Lane, folder: Path, origin: float) -> dict:
    folder.mkdir()
    temporary = folder / "temp"
    temporary.mkdir()
    if lane.kind == "pytest":
        command = [sys.executable, "-m", "pytest", "-q", *lane_files(root, lane),
                   "--basetemp", str(folder / "pytest-tmp"),
                   "-o", f"cache_dir={folder / 'pytest-cache'}", "--junitxml", str(folder / "junit.xml")]
    else:
        command = [arg.replace("{python}", sys.executable).replace("{artifact}", str(folder))
                   for arg in lane.command]
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("MIRA_") and key not in {
               "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "OPENAI_API_KEY", "TYPESAFE_API_KEY",
               "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_QUOTA_PROJECT",
               "CODEX_ACCESS_TOKEN", "ACCESS_TOKEN", "AZURE_OPENAI_API_KEY", "ANTHROPIC_API_KEY",
           }}
    env.update(TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary),
               MIRA_TEST_RUN_DIR=str(folder), PYTHONDONTWRITEBYTECODE="1")
    started = time.monotonic()
    pid = None
    status, code = "failed", 127
    with (folder / "stdout.txt").open("w", encoding="utf-8") as out, \
         (folder / "stderr.txt").open("w", encoding="utf-8") as err:
        try:
            process = subprocess.Popen(command, cwd=root, env=env, stdout=out, stderr=err,
                                       start_new_session=os.name == "posix")
            pid = process.pid
            try:
                code = process.wait(timeout=lane.timeout)
                status = "passed" if code == 0 else "no_tests" if code == 5 else "failed"
            except subprocess.TimeoutExpired:
                _stop(process)
                code, status = 124, "timed_out"
        except OSError as error:
            err.write(f"{type(error).__name__}: {error}\n")
    ended = time.monotonic()
    counts = _test_counts(folder)
    if lane.kind == "pytest" and code == 0 and (counts is None or counts["tests"] == 0):
        status, code = "missing_test_evidence", 1
    result = {"name": lane.name, "status": status, "exit_code": code, "pid": pid,
              "command": command, "serial": lane.serial, "timeout_seconds": lane.timeout,
              "started_offset": started - origin, "ended_offset": ended - origin,
              "duration_seconds": ended - started, "tests": counts,
              "stdout_sha256": hashlib.sha256((folder / "stdout.txt").read_bytes()).hexdigest(),
              "stderr_sha256": hashlib.sha256((folder / "stderr.txt").read_bytes()).hexdigest()}
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def run_plan(root: Path, plan: Plan, *, jobs: int = 3,
             output_dir: Path | None = None) -> dict:
    if not isinstance(jobs, int) or isinstance(jobs, bool) or not 1 <= jobs <= 8:
        raise PlanError("jobs must be an integer between 1 and 8; no nested worker pools")
    root = root.resolve()
    folder = (output_dir or root / "var/quality" / uuid.uuid4().hex).resolve()
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise PlanError("run directory already exists; choose a new path") from error
    before = fingerprints(root)
    started_at = datetime.now(UTC).isoformat()
    origin = time.monotonic()
    (folder / "plan.json").write_text(json.dumps(asdict(plan), ensure_ascii=False, indent=2) + "\n")
    results: dict[str, dict] = {}
    parallel = [lane for lane in plan.lanes if not lane.serial]
    serial = [lane for lane in plan.lanes if lane.serial]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(_execute, root, lane, folder / lane.name, origin): lane for lane in parallel}
        for future in as_completed(futures):
            lane = futures[future]
            results[lane.name] = future.result()
            print(f"[{lane.name}] {results[lane.name]['status']}", file=sys.stderr, flush=True)
    for lane in serial:
        if any(item["status"] != "passed" for item in results.values()):
            break  # Expensive release checks do not hide earlier failures or start unnecessarily.
        results[lane.name] = _execute(root, lane, folder / lane.name, origin)
        print(f"[{lane.name}] {results[lane.name]['status']}", file=sys.stderr, flush=True)
    after = fingerprints(root)
    changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    status = "no_checks" if not plan.lanes else "passed"
    if len(results) != len(plan.lanes) or any(item["status"] != "passed" for item in results.values()):
        status = "failed"
    if changed:
        status = "source_changed"
    summary = {
        "status": status, "scope": plan.mode, "changed_paths": list(plan.changed),
        "selection_reasons": list(plan.reasons), "selected_lanes": [x.name for x in plan.lanes],
        "not_run": [name for name in plan.all_lanes if name not in results],
        "lanes": [results[lane.name] for lane in plan.lanes if lane.name in results],
        "jobs": jobs, "started_at": started_at, "ended_at": datetime.now(UTC).isoformat(),
        "duration_seconds": time.monotonic() - origin, "python": sys.version,
        "platform": platform.platform(), "source_before_digest": digest(before),
        "source_after_digest": digest(after), "changed_during_run": changed,
        "source_files": before, "output_dir": str(folder),
        "limitations": "Local automated checks only; not selected means not_run, not cached pass. "
                        "No provider, browser-device or original architecture acceptance implied.",
    }
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary
