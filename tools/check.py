"""Scoped quality entrypoint. Default: affected changes; full/release are explicit."""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.quality_plan import PlanError, changed_paths, load_catalog, plan_for_changes, plan_for_lanes
from tools.quality_run import run_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--affected", action="store_true", help="default: git worktree changes")
    group.add_argument("--files", nargs="+", help="explicit repository-relative changed paths (zip users)")
    group.add_argument("--lane", nargs="+", help="exact lanes for focused GREEN; not a merge impact check")
    group.add_argument("--full", action="store_true", help="all offline quality lanes")
    group.add_argument("--release", action="store_true", help="full plus serial wheel/loopback checks")
    parser.add_argument("--base", help="include committed changes since merge-base with this Git reference")
    parser.add_argument("--jobs", type=int, default=3, help="bounded process concurrency, 1..8; default 3")
    parser.add_argument("--plan", action="store_true", help="print selection without running tests")
    parser.add_argument("--matrix", action="store_true", help="print CI matrix; never runs tests")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--output-dir", type=Path, help="new, never overwritten artifact directory")
    args = parser.parse_args()
    try:
        if args.list:
            for lane in load_catalog(ROOT).lanes:
                print(f"{lane.name:14} {lane.kind:8} {'release/serial' if lane.serial else 'parallel/offline'}")
            return 0
        if not 1 <= args.jobs <= 8:
            raise PlanError("--jobs must be between 1 and 8")
        if args.base and (args.files or args.lane or args.full or args.release):
            raise PlanError("--base belongs to --affected, not explicit files/lanes/full/release")
        if args.full or args.release:
            plan = plan_for_lanes(ROOT, [], mode="release" if args.release else "full")
        elif args.lane:
            plan = plan_for_lanes(ROOT, args.lane)
        else:
            paths = args.files if args.files is not None else changed_paths(ROOT, args.base)
            plan = plan_for_changes(ROOT, paths)
        if args.matrix:
            print(json.dumps({"include": [{"lane": x.name} for x in plan.lanes]}))
            return 0
        if args.plan:
            print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
            return 0
        print("Selection: " + (", ".join(lane.name for lane in plan.lanes) or "none"))
        for reason in plan.reasons:
            print("  " + reason)
        report = run_plan(ROOT, plan, jobs=args.jobs, output_dir=args.output_dir)
        print(f"{report['status']} (scope={report['scope']}); not_run={', '.join(report['not_run']) or 'none'}")
        print("Report: " + str(Path(report["output_dir"]) / "summary.json"))
        return 0 if report["status"] in {"passed", "no_checks"} else 1
    except PlanError as error:
        print(f"Selection error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
