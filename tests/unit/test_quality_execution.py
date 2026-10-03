"""Real synthetic child processes; barriers prove overlap, not speed claims."""
import json
import sys
from pathlib import Path

import pytest

from tools.quality_plan import Lane, Plan, PlanError
from tools.quality_run import run_plan


def lane(name, code, **kwargs):
    return Lane(name, "command", command=(sys.executable, "-c", code), **kwargs)


def test_two_lanes_really_overlap_and_get_isolated_temp_and_logs(tmp_path):
    code = '''import os, time
from pathlib import Path
root=Path(%r)
name=%r
root.joinpath(name).write_text(os.environ['MIRA_TEST_RUN_DIR'])
deadline=time.monotonic()+10
while not all(root.joinpath(n).exists() for n in ('a','b')):
    assert time.monotonic()<deadline, 'second lane never ran concurrently'
    time.sleep(.01)
print(name, os.getpid(), os.environ['TMPDIR'])
'''
    plan = Plan("lanes", (lane("a", code % (str(tmp_path), "a")),
                          lane("b", code % (str(tmp_path), "b"))), ("a", "b", "not-selected"))
    report = run_plan(tmp_path, plan, jobs=2, output_dir=tmp_path / "out")
    assert report["status"] == "passed" and report["scope"] == "lanes"
    assert report["not_run"] == ["not-selected"]
    results = report["lanes"]
    assert all(r["exit_code"] == 0 for r in results)
    assert max(r["started_offset"] for r in results) < min(r["ended_offset"] for r in results)
    assert (tmp_path / "a").read_text() != (tmp_path / "b").read_text()
    assert len({r["pid"] for r in results}) == 2
    assert (tmp_path / "out/a/stdout.txt").read_text().startswith("a ")
    assert (tmp_path / "out/b/stdout.txt").read_text().startswith("b ")


def test_failed_lane_is_reported_but_other_lane_results_are_not_lost(tmp_path):
    plan = Plan("affected", (lane("bad", "raise SystemExit(1)"), lane("good", "print('ok')")),
                ("bad", "good", "omitted"), changed=("some.py",))
    report = run_plan(tmp_path, plan, jobs=2, output_dir=tmp_path / "out")
    assert report["status"] == "failed"
    assert {r["name"]: r["status"] for r in report["lanes"]} == {"bad": "failed", "good": "passed"}
    assert report["not_run"] == ["omitted"]
    assert json.loads((tmp_path / "out/summary.json").read_text())["status"] == "failed"


def test_serial_lane_runs_after_parallel_group(tmp_path):
    marker = tmp_path / "done"
    work = lane("work", f"from pathlib import Path; Path({str(marker)!r}).touch()")
    serial = lane("exclusive", f"from pathlib import Path; assert Path({str(marker)!r}).exists()", serial=True)
    report = run_plan(tmp_path, Plan("release", (work, serial), ("work", "exclusive")),
                      jobs=2, output_dir=tmp_path / "out")
    assert report["status"] == "passed"
    rows = {r["name"]: r for r in report["lanes"]}
    assert rows["exclusive"]["started_offset"] >= rows["work"]["ended_offset"]


def test_timeout_is_not_a_skip_or_pass(tmp_path):
    slow = lane("slow", "import time; time.sleep(60)", timeout=.1)
    report = run_plan(tmp_path, Plan("lanes", (slow,), ("slow",)), output_dir=tmp_path / "out")
    assert report["status"] == "failed"
    assert report["lanes"][0]["status"] == "timed_out"
    assert report["lanes"][0]["exit_code"] == 124


def test_pytest_no_tests_exit_is_not_success(tmp_path):
    empty = lane("empty", "raise SystemExit(5)")
    report = run_plan(tmp_path, Plan("lanes", (empty,), ("empty",)), output_dir=tmp_path / "out")
    assert report["status"] == "failed" and report["lanes"][0]["exit_code"] == 5


def test_missing_binary_produces_failed_receipt(tmp_path):
    missing = Lane("missing", "command", command=("mira-missing-test-binary",))
    report = run_plan(tmp_path, Plan("lanes", (missing,), ("missing",)), output_dir=tmp_path / "out")
    assert report["status"] == "failed" and report["lanes"][0]["exit_code"] == 127


def test_existing_run_directory_is_never_overwritten(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    (output / "preserved").write_text("old")
    with pytest.raises(PlanError):
        run_plan(tmp_path, Plan("lanes", (), ()), output_dir=output)
    assert (output / "preserved").read_text() == "old"


def test_empty_plan_reports_no_checks_not_suite_passed(tmp_path):
    report = run_plan(tmp_path, Plan("documentation-only", (), ("domain",)),
                      output_dir=tmp_path / "out")
    assert report["status"] == "no_checks" and report["not_run"] == ["domain"]


@pytest.mark.parametrize("jobs", [0, -1, 33])
def test_invalid_parallel_budget_rejected(tmp_path, jobs):
    with pytest.raises(PlanError):
        run_plan(tmp_path, Plan("lanes", (), ()), jobs=jobs, output_dir=tmp_path / "out")


def test_code_modified_during_execution_cannot_be_reported_green(tmp_path):
    (tmp_path / "config").mkdir()
    source = tmp_path / "config/defaults.toml"
    source.write_text("old")
    mutate = lane("mutate", f"from pathlib import Path; Path({str(source)!r}).write_text('new')")
    report = run_plan(tmp_path, Plan("lanes", (mutate,), ("mutate",)), output_dir=tmp_path / "out")
    assert report["status"] == "source_changed"
    assert report["changed_during_run"] == ["config/defaults.toml"]


@pytest.mark.parametrize("relative", [
    "apps/web/index.html", "apps/web/public/app.css",
    "apps/web/public/audio/capture-worklet.js", "apps/web/public/scene/mira.svg", "setup.py",
])
def test_browser_and_package_inputs_modified_during_execution_are_not_green(tmp_path, relative):
    source = tmp_path / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("old")
    mutate = lane("mutate", f"from pathlib import Path; Path({str(source)!r}).write_text('new')")
    report = run_plan(tmp_path, Plan("lanes", (mutate,), ("mutate",)), output_dir=tmp_path / "out")
    assert report["status"] == "source_changed"
    assert report["changed_during_run"] == [relative]


def test_evidence_recorder_uses_complete_quality_source_boundary(tmp_path, monkeypatch):
    from tools import record_check
    from tools.quality_run import fingerprints
    paths = ("apps/web/index.html", "apps/web/tsconfig.json", "apps/web/public/app.css",
             "setup.py", "packages/contracts/openapi.json", "scripts/dev")
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source")
    monkeypatch.setattr(record_check, "ROOT", tmp_path)
    assert record_check.fingerprints() == fingerprints(tmp_path)
    assert set(record_check.fingerprints()) == set(paths)
