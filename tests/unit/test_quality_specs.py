"""The specs lane must not hide a full pytest collection in every edit cycle."""
from pathlib import Path

import pytest

from tools.check_specs import SpecLinkError, mapped_test_files


def manifest(*nodes):
    return {"requirements": [{"tests": list(nodes)}]}


def test_spec_collection_uses_only_mapped_modules_once(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_one.py").touch()
    (tests / "test_two.py").touch()
    (tests / "test_unrelated.py").touch()
    result = mapped_test_files(tmp_path, [manifest(
        "tests/test_one.py::test_a", "tests/test_one.py::test_b[case]",
        "tests/test_two.py::TestClass::test_c")])
    assert result == ["tests/test_one.py", "tests/test_two.py"]


@pytest.mark.parametrize("node", ["../private.py::test_a", "/tmp/test_a.py::test_a",
                                   "tests/missing.py::test_a", "--collect-only", "tests/data.json::test_a"])
def test_spec_collection_rejects_missing_or_nonlocal_nodes(tmp_path, node):
    with pytest.raises(SpecLinkError):
        mapped_test_files(tmp_path, [manifest(node)])


def test_empty_mapping_cannot_fall_back_to_collect_everything(tmp_path):
    with pytest.raises(SpecLinkError):
        mapped_test_files(tmp_path, [])
