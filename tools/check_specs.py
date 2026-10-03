"""Check requirement-to-test links, not semantic correctness or product acceptance."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SpecLinkError(ValueError):
    pass


def validate_feature(root: Path, manifest: dict, collected_tests: set[str]) -> int:
    """Pure validation with explicit inputs; the CLI alone collects pytest node IDs."""
    if set(manifest) != {"feature", "spec", "requirements"}:
        raise SpecLinkError("manifest fields do not match the contract")
    feature = manifest["feature"]
    if not isinstance(feature, str) or not re.fullmatch(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*", feature):
        raise SpecLinkError("invalid feature identifier")
    prefix = re.escape(feature.replace("-", ""))
    spec = Path(manifest["spec"])
    if spec.is_absolute() or ".." in spec.parts or not (root / spec).is_file():
        raise SpecLinkError("spec path must name an existing file within the project")
    identifiers = re.findall(rf"^### ({prefix}-\d{{3}})\b", (root / spec).read_text(), re.MULTILINE)
    if not identifiers or len(identifiers) != len(set(identifiers)):
        raise SpecLinkError("missing or duplicate requirement headings")
    rows = manifest["requirements"]
    if not isinstance(rows, list) or not rows:
        raise SpecLinkError("requirements must be a nonempty list")
    row_ids = []
    for row in rows:
        if set(row) != {"id", "tests"}:
            raise SpecLinkError("each mapping has only id and tests")
        row_ids.append(row["id"])
        if not isinstance(row["tests"], list) or not row["tests"]:
            raise SpecLinkError("each requirement needs at least one collected test")
        for node in row["tests"]:
            if node not in collected_tests:
                raise SpecLinkError(f"test is not collected: {node}")
    if len(row_ids) != len(set(row_ids)) or set(row_ids) != set(identifiers):
        raise SpecLinkError("requirement headings and mapping must match exactly")
    return len(rows)


def main() -> None:
    manifests = sorted((ROOT / "specs/features").glob("*/traceability.json"))
    if not manifests:
        raise SystemExit("No feature traceability manifests were found.")
    documents = [(path, json.loads(path.read_text())) for path in manifests]
    targets = mapped_test_files(ROOT, [data for _, data in documents])
    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", *targets],
                               cwd=ROOT, capture_output=True, text=True, timeout=60)
    if collected.returncode:
        print(collected.stdout, end="")
        print(collected.stderr, end="", file=sys.stderr)
        raise SystemExit(collected.returncode)
    nodes = {line.strip().split("[", 1)[0] for line in collected.stdout.splitlines()
             if line.startswith("tests/") and "::" in line}
    total = 0
    for path, data in documents:
        try:
            total += validate_feature(ROOT, data, nodes)
        except (SpecLinkError, ValueError, TypeError, KeyError) as error:
            raise SystemExit(f"{path.relative_to(ROOT)}: {error}") from None
    print(f"Spec links: {total} requirements reference collected tests; this is not execution evidence.")


def mapped_test_files(root: Path, manifests: list[dict]) -> list[str]:
    """Collect explicit mapped modules once; an empty list must not mean all tests."""
    result: set[str] = set()
    try:
        for manifest in manifests:
            for row in manifest["requirements"]:
                for node in row["tests"]:
                    if not isinstance(node, str) or "::" not in node:
                        raise SpecLinkError("spec tests must be explicit pytest node IDs")
                    path = Path(node.split("::", 1)[0])
                    if (path.is_absolute() or ".." in path.parts or path.suffix != ".py"
                            or not (root / path).is_file()
                            or not (root / path).resolve().is_relative_to(root.resolve())):
                        raise SpecLinkError("spec test must name an existing local Python module")
                    result.add(path.as_posix())
    except (KeyError, TypeError) as error:
        raise SpecLinkError("invalid test mapping") from error
    if not result:
        raise SpecLinkError("no mapped test modules; refuse an implicit full collection")
    return sorted(result)


if __name__ == "__main__":
    main()
