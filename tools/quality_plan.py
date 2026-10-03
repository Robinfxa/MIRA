"""Declarative test ownership and conservative impact selection. No test execution."""
import fnmatch
import json
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class PlanError(ValueError):
    """Selection cannot safely be made; never substitute an empty green plan."""


@dataclass(frozen=True)
class Lane:
    name: str
    kind: str
    targets: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    serial: bool = False
    timeout: float = 60
    default: bool = True


@dataclass(frozen=True)
class Catalog:
    lanes: tuple[Lane, ...]
    rules: tuple[dict, ...]
    full_patterns: tuple[str, ...]
    documentation_patterns: tuple[str, ...]
    guards: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    mode: str
    lanes: tuple[Lane, ...]
    all_lanes: tuple[str, ...]
    changed: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def _strings(value: object, label: str, *, empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not empty):
        raise PlanError(f"{label} must be a list")
    if any(not isinstance(v, str) or not v for v in value):
        raise PlanError(f"{label} contains an invalid string")
    return tuple(value)


def _relative(path: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("-") or "\x00" in path:
        raise PlanError("changed paths must be repository-relative names")
    path = path.replace("\\", "/")
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or ":" in path or str(pure) == ".":
        raise PlanError("changed paths must stay inside the repository")
    return pure.as_posix()


def load_catalog(root: Path) -> Catalog:
    try:
        data = tomllib.loads((root / "tests/quality.toml").read_text(encoding="utf-8"))
        if set(data) != {"version", "guards", "full_patterns", "documentation_patterns", "lanes", "rules"}:
            raise PlanError("unknown or missing catalog fields")
        if data["version"] != 1:
            raise PlanError("unsupported test catalog version")
        lanes = []
        for row in data["lanes"]:
            if set(row) - {"name", "kind", "targets", "command", "serial", "timeout", "default"}:
                raise PlanError("unknown lane field")
            name, kind = row["name"], row["kind"]
            if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or kind not in {"pytest", "command"}:
                raise PlanError("invalid lane name or kind")
            targets = _strings(row.get("targets", []), "targets", empty=kind != "pytest")
            for target in targets:
                _relative(target)
            command = _strings(row.get("command", []), "command", empty=kind == "pytest")
            if kind == "pytest" and command:
                raise PlanError("pytest lane must use targets, not custom command")
            for flag in ("serial", "default"):
                if flag in row and not isinstance(row[flag], bool):
                    raise PlanError(f"{flag} must be a boolean")
            timeout = row.get("timeout", 60)
            if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not 0 < timeout <= 600:
                raise PlanError("lane timeout must be >0 and <=600 seconds")
            lanes.append(Lane(name, kind, targets, command, row.get("serial", False),
                              timeout, row.get("default", True)))
        known = {lane.name for lane in lanes}
        if not lanes or len(known) != len(lanes):
            raise PlanError("lane names must be nonempty and unique")
        guards = _strings(data["guards"], "guards")
        rules = []
        for rule in data["rules"]:
            if set(rule) != {"paths", "lanes"}:
                raise PlanError("rule must have paths and lanes")
            paths = _strings(rule["paths"], "paths")
            members = _strings(rule["lanes"], "lanes")
            if set(members) - known:
                raise PlanError("rule refers to an unknown lane")
            rules.append({"paths": paths, "lanes": members})
        if set(guards) - known:
            raise PlanError("unknown guard lane")
        return Catalog(tuple(lanes), tuple(rules), _strings(data["full_patterns"], "full_patterns"),
                       _strings(data["documentation_patterns"], "documentation_patterns"), guards)
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as error:
        raise PlanError(f"invalid tests/quality.toml: {error}") from error


def lane_files(root: Path, lane: Lane) -> tuple[str, ...]:
    paths: set[str] = set()
    for pattern in lane.targets:
        matches = [p for p in root.glob(pattern) if p.is_file()]
        if not matches:
            raise PlanError(f"{lane.name}: target matched no files: {pattern}")
        paths.update(p.relative_to(root).as_posix() for p in matches)
    return tuple(sorted(paths))


def validate_inventory(root: Path, catalog: Catalog) -> None:
    discovered = {p.relative_to(root).as_posix() for p in (root / "tests").rglob("test_*.py")}
    discovered |= {p.relative_to(root).as_posix() for p in (root / "tests").rglob("*_test.py")}
    discovered |= {p.relative_to(root).as_posix() for p in (root / "tests").rglob("*.test.mjs")}
    owners: dict[str, list[str]] = {}
    for lane in catalog.lanes:
        for path in lane_files(root, lane):
            owners.setdefault(path, []).append(lane.name)
    unowned = discovered - owners.keys()
    multiple = [path for path, lanes in owners.items() if len(lanes) > 1]
    if unowned:
        raise PlanError("unowned tests: " + ", ".join(sorted(unowned)))
    if multiple:
        raise PlanError("tests with multiple owners: " + ", ".join(sorted(multiple)))


def _make(catalog: Catalog, selected: set[str], mode: str, paths=(), reasons=()) -> Plan:
    unknown = selected - {lane.name for lane in catalog.lanes}
    if unknown:
        raise PlanError("unknown lanes: " + ", ".join(sorted(unknown)))
    return Plan(mode, tuple(lane for lane in catalog.lanes if lane.name in selected),
                tuple(lane.name for lane in catalog.lanes), tuple(paths), tuple(reasons))


def plan_for_lanes(root: Path, names: list[str], *, mode: str = "lanes") -> Plan:
    catalog = load_catalog(root)
    validate_inventory(root, catalog)
    if mode not in {"full", "release", "lanes"}:
        raise PlanError("unknown selection mode")
    selected = set(names) if mode == "lanes" else {
        lane.name for lane in catalog.lanes if lane.default or mode == "release"}
    if mode == "lanes" and not selected:
        raise PlanError("explicit lane selection must not be empty")
    return _make(catalog, selected, mode, reasons=(f"explicit {mode} selection",))


def plan_for_changes(root: Path, paths: list[str]) -> Plan:
    catalog = load_catalog(root)
    validate_inventory(root, catalog)
    normalized = tuple(sorted({_relative(path) for path in paths}))
    if not normalized:
        return _make(catalog, set(), "no-changes", reasons=("no changed paths; no tests executed",))
    all_default = {lane.name for lane in catalog.lanes if lane.default}
    selected: set[str] = set()
    reasons: list[str] = []
    for path in normalized:
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in catalog.full_patterns):
            selected |= all_default
            reasons.append(f"{path}: shared seam -> all offline lanes")
            continue
        owners = {lane.name for lane in catalog.lanes
                  if any(fnmatch.fnmatchcase(path, pattern) for pattern in lane.targets)}
        matched = owners | {name for rule in catalog.rules
                            if any(fnmatch.fnmatchcase(path, p) for p in rule["paths"])
                            for name in rule["lanes"]}
        if path.startswith("specs/features/") and len(PurePosixPath(path).parts) >= 4:
            feature_dir = root.joinpath(*PurePosixPath(path).parts[:3])
            mapping = feature_dir / "traceability.json"
            if not mapping.is_file():
                matched |= all_default
                reasons.append(f"{path}: missing/deleted feature mapping -> all offline lanes")
            else:
                try:
                    document = json.loads(mapping.read_text())
                    for requirement in document["requirements"]:
                        for node in requirement["tests"]:
                            module = _relative(node.split("::", 1)[0])
                            mapped = {lane.name for lane in catalog.lanes
                                      if any(fnmatch.fnmatchcase(module, target) for target in lane.targets)}
                            if not mapped:
                                raise PlanError(f"unowned mapped test module: {module}")
                            matched |= mapped
                except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
                    raise PlanError(f"invalid feature mapping: {mapping.relative_to(root)}") from error
        if matched:
            selected |= matched
            reasons.append(f"{path}: owners/consumers -> {', '.join(sorted(matched))}")
        elif any(fnmatch.fnmatchcase(path, p) for p in catalog.documentation_patterns):
            reasons.append(f"{path}: documentation only; no runtime tests implied")
        else:
            selected |= all_default
            reasons.append(f"{path}: unmapped -> all offline lanes (register its impact rule)")
    if selected:
        selected |= set(catalog.guards)
    return _make(catalog, selected, "affected" if selected else "documentation-only", normalized, reasons)


def changed_paths(root: Path, base: str | None = None) -> list[str]:
    def git(*args: str) -> str:
        try:
            result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PlanError("Git unavailable; use --files, --lane or --full explicitly") from error
        if result.returncode:
            raise PlanError("Git comparison failed; use a valid --base or explicit --files/--lane/--full")
        return result.stdout

    if Path(git("rev-parse", "--show-toplevel").strip()).resolve() != root.resolve():
        raise PlanError("run must target the repository root, not an unrelated parent repository")
    commands = [("diff", "--name-only", "--no-renames", "-z"),
                ("diff", "--cached", "--name-only", "--no-renames", "-z"),
                ("ls-files", "--others", "--exclude-standard", "-z")]
    if base is not None:
        if not base or base.startswith("-"):
            raise PlanError("invalid base reference")
        ancestor = git("merge-base", base, "HEAD").strip()
        commands.append(("diff", "--name-only", "--no-renames", "-z", ancestor, "HEAD", "--"))
    return sorted({_relative(path) for command in commands for path in git(*command).split("\x00") if path})
