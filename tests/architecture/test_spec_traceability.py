"""Negative examples prove the SDD link check has teeth, rather than just counting files."""
import copy

import pytest

from tools.check_specs import SpecLinkError, validate_feature

NODE = "tests/contracts/test_example.py::test_behavior"


@pytest.fixture
def mapping(tmp_path):
    (tmp_path / "spec.md").write_text("# Example\n### FND02-001 Input contract\n")
    return tmp_path, {"feature": "FND-02", "spec": "spec.md",
                      "requirements": [{"id": "FND02-001", "tests": [NODE]}]}


def test_spec_mapping_resolves_a_collected_test(mapping):
    root, data = mapping
    assert validate_feature(root, data, {NODE}) == 1


def test_nonexistent_test_is_not_accepted(mapping):
    root, data = mapping
    with pytest.raises(SpecLinkError, match="not collected"):
        validate_feature(root, data, set())


def test_missing_requirement_mapping_fails(mapping):
    root, data = mapping
    (root / "spec.md").write_text("### FND02-001 A\n### FND02-002 B\n")
    with pytest.raises(SpecLinkError, match="match exactly"):
        validate_feature(root, data, {NODE})


def test_duplicate_mapping_fails(mapping):
    root, data = mapping
    data["requirements"] *= 2
    with pytest.raises(SpecLinkError, match="match exactly"):
        validate_feature(root, data, {NODE})


def test_duplicate_spec_heading_fails(mapping):
    root, data = mapping
    (root / "spec.md").write_text("### FND02-001 A\n### FND02-001 B\n")
    with pytest.raises(SpecLinkError, match="duplicate"):
        validate_feature(root, data, {NODE})


@pytest.mark.parametrize("path", ["../outside.md", "/absolute.md", "missing.md"])
def test_spec_path_is_local_and_existing(mapping, path):
    root, data = mapping
    with pytest.raises(SpecLinkError, match="path"):
        validate_feature(root, data | {"spec": path}, {NODE})


def test_empty_test_list_cannot_count_as_coverage(mapping):
    root, data = mapping
    data["requirements"][0]["tests"] = []
    with pytest.raises(SpecLinkError, match="at least one"):
        validate_feature(root, data, {NODE})


def test_editing_status_cannot_manufacture_verification(mapping):
    root, data = mapping
    data = copy.deepcopy(data)
    data["requirements"][0]["status"] = "passed"
    with pytest.raises(SpecLinkError, match="only id and tests"):
        validate_feature(root, data, {NODE})


def test_checker_supports_the_next_feature_without_editing_tool_code(mapping):
    root, data = mapping
    (root / "spec.md").write_text("### FND03-001 Next feature\n")
    data["feature"] = "FND-03"
    data["requirements"][0]["id"] = "FND03-001"
    assert validate_feature(root, data, {NODE}) == 1


def test_checker_rejects_a_manifest_pointing_at_another_features_ids(mapping):
    root, data = mapping
    data["feature"] = "FND-03"
    with pytest.raises(SpecLinkError):
        validate_feature(root, data, {NODE})
