"""FND-03: selection is explicit, conservative at shared seams, and fail-closed."""
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from tools.quality_plan import (
    PlanError, changed_paths, load_catalog, plan_for_changes, plan_for_lanes, validate_inventory,
)

ROOT = Path(__file__).resolve().parents[2]


def names(plan):
    return {lane.name for lane in plan.lanes}


def test_replay_change_selects_consumers_not_frontend_or_full_collection():
    plan = plan_for_changes(ROOT, ["apps/api/src/mira/adapters/generation/replay/backend.py"])
    assert names(plan) == {"architecture", "providers", "config", "actor", "http"}
    assert plan.mode == "affected" and plan.changed


def test_frontend_change_selects_web_and_small_architecture_guard():
    plan = plan_for_changes(ROOT, ["apps/web/src/features/presentation/permit-gate.ts"])
    assert names(plan) == {"architecture", "web"}


@pytest.mark.parametrize("path", [
    "apps/api/src/mira/domain/transitions.py", "apps/api/src/mira/entrypoints/http/schemas.py",
    "apps/api/src/mira/application/ports/generation.py", "requirements/dev.lock",
    "tests/conftest.py", "tests/support/barriers.py", "tests/quality.toml", "package-lock.json",
])
def test_shared_contract_or_fixture_expands_to_all_offline_lanes(path):
    assert names(plan_for_changes(ROOT, [path])) == names(plan_for_lanes(ROOT, [], mode="full"))


def test_unknown_path_falls_back_loudly_instead_of_guessing_no_impact():
    plan = plan_for_changes(ROOT, ["new-runtime/unknown.py"])
    assert names(plan) == names(plan_for_lanes(ROOT, [], mode="full"))
    assert any("unmapped" in reason for reason in plan.reasons)


def test_docs_only_and_clean_tree_have_explicit_empty_scope():
    docs = plan_for_changes(ROOT, ["docs/handoff/FND-03.md"])
    clean = plan_for_changes(ROOT, [])
    assert not docs.lanes and not clean.lanes
    assert docs.mode == "documentation-only" and clean.mode == "no-changes"


@pytest.mark.parametrize("path", ["../private.py", "/tmp/file.py", "--full", "a/../../b", ""])
def test_explicit_paths_cannot_escape_repository_or_become_flags(path):
    with pytest.raises(PlanError):
        plan_for_changes(ROOT, [path])


def test_deleted_source_path_still_selects_its_consumers():
    plan = plan_for_changes(ROOT, ["apps/api/src/mira/adapters/generation/deleted.py"])
    assert {"providers", "actor", "http"} <= names(plan)


def test_direct_test_change_selects_its_lane():
    plan = plan_for_changes(ROOT, ["tests/unit/test_actor.py"])
    assert names(plan) == {"architecture", "actor"}


def test_explicit_lanes_deduplicate_and_unknown_lane_fails():
    assert names(plan_for_lanes(ROOT, ["actor", "actor"])) == {"actor"}
    with pytest.raises(PlanError, match="unknown"):
        plan_for_lanes(ROOT, ["actro"])


def test_full_excludes_external_smoke_and_package_but_release_includes_them():
    assert not ({"smoke", "package"} & names(plan_for_lanes(ROOT, [], mode="full")))
    assert {"smoke", "package"} <= names(plan_for_lanes(ROOT, [], mode="release"))


def test_every_test_file_has_exactly_one_owner():
    validate_inventory(ROOT, load_catalog(ROOT))


def test_new_unassigned_test_is_a_selection_error(tmp_path):
    shutil.copytree(ROOT / "tests", tmp_path / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "tests/unit/test_unowned.py").write_text("def test_new(): pass\n")
    with pytest.raises(PlanError, match="unowned"):
        validate_inventory(tmp_path, load_catalog(tmp_path))


def test_overlapping_owners_fail_instead_of_double_counting():
    catalog = load_catalog(ROOT)
    duplicate = replace(catalog.lanes[0], name="duplicate")
    with pytest.raises(PlanError, match="multiple"):
        validate_inventory(ROOT, replace(catalog, lanes=(*catalog.lanes, duplicate)))


def test_misspelled_lane_manifest_field_fails(tmp_path):
    (tmp_path / "tests").mkdir()
    text = (ROOT / "tests/quality.toml").read_text().replace('name = "actor"', 'nmae = "actor"')
    (tmp_path / "tests/quality.toml").write_text(text)
    with pytest.raises(PlanError):
        load_catalog(tmp_path)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, text=True,
                          capture_output=True).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "local-test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    for name in ("staged.py", "unstaged.py", "deleted.py", "old name.py"):
        (tmp_path / name).write_text("baseline\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


def test_diff_includes_staged_unstaged_untracked_deleted_and_both_rename_paths(repository):
    root = repository
    (root / "staged.py").write_text("staged\n")
    git(root, "add", "staged.py")
    (root / "unstaged.py").write_text("unstaged\n")
    (root / "deleted.py").unlink()
    git(root, "mv", "old name.py", "new name.py")
    (root / "untracked with space.py").write_text("new\n")
    assert set(changed_paths(root)) == {
        "staged.py", "unstaged.py", "deleted.py", "old name.py", "new name.py",
        "untracked with space.py",
    }


def test_base_diff_includes_committed_and_current_work(repository):
    base = git(repository, "rev-parse", "HEAD")
    (repository / "staged.py").write_text("commit this\n")
    git(repository, "add", ".")
    git(repository, "commit", "-qm", "feature")
    (repository / "new.py").write_text("not committed\n")
    assert set(changed_paths(repository, base)) == {"staged.py", "new.py"}


def test_bad_base_and_missing_repository_are_errors_not_clean_pass(repository, tmp_path):
    with pytest.raises(PlanError):
        changed_paths(repository, "missing-base")
    nested = repository / "nested"
    nested.mkdir()
    with pytest.raises(PlanError):
        changed_paths(nested)


def test_feature_spec_change_selects_actual_mapped_behavior_lanes():
    plan = plan_for_changes(ROOT, ["specs/features/FND-02-fixture-replay/spec.md"])
    assert {"providers", "actor", "http", "architecture", "tooling", "specs"} <= names(plan)
    assert "web" not in names(plan)


def test_pytest_suffix_named_files_cannot_escape_inventory(tmp_path):
    shutil.copytree(ROOT / "tests", tmp_path / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "tests/unit/forgotten_test.py").write_text("def test_behavior(): pass\n")
    with pytest.raises(PlanError, match="unowned"):
        validate_inventory(tmp_path, load_catalog(tmp_path))
