"""Check saved local evidence integrity; hashes are not independent authenticity attestation."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "docs/verification/fnd-02/runs"
PAIRS = (
    ("002-red-replay", "003-green-replay", ("tests/contracts/test_replay_generation.py",)),
    ("004-red-script-hardening", "005-green-script-hardening", (
        "tests/contracts/test_replay_generation.py", "tests/contracts/test_replay_script.py",
        "tests/contracts/test_replay_cancellation.py")),
    ("008-red-reusable-sdd-check", "009-green-reusable-sdd-check", (
        "tests/architecture/test_spec_traceability.py",)),
)


def main() -> None:
    reports = {}
    for path in sorted(RUNS.glob("*/report.json")):
        data = json.loads(path.read_text())
        for stream in ("stdout", "stderr"):
            actual = hashlib.sha256((path.parent / f"{stream}.txt").read_bytes()).hexdigest()
            if actual != data[f"{stream}_sha256"]:
                raise SystemExit(f"Changed evidence: {path.parent.name}/{stream}.txt")
        if data["source_before"] != data["source_after"]:
            raise SystemExit(f"Tracked source changed during run: {path.parent.name}")
        reports[data["run_id"]] = data
    for red_id, green_id, files in PAIRS:
        red, green = reports[red_id], reports[green_id]
        if red["exit_code"] != 1 or green["exit_code"] != 0:
            raise SystemExit(f"Missing expected RED/GREEN outcomes: {red_id}")
        if red["command"] != green["command"] or red["started_at"] >= green["started_at"]:
            raise SystemExit(f"Inconsistent command or chronology: {red_id}")
        for file in files:
            if red["source_before"][file] != green["source_before"][file]:
                raise SystemExit(f"Test changed within pair: {file}")
    print(f"{len(reports)} local logs verified; {len(PAIRS)} real RED/GREEN pairs used unchanged tests.")
    print("This verifies recorded bytes and ordering, not independent human or provider acceptance.")


if __name__ == "__main__":
    main()
