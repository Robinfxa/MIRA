"""The JS shell and Python package describe the same MIRA source release."""
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def test_distribution_name_and_version_match_lock_and_python():
    package = json.loads((ROOT / "package.json").read_text())
    lock = json.loads((ROOT / "package-lock.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    for field in ("name", "version"):
        assert package[field] == lock[field] == lock["packages"][""][field] == project[field]


def test_declared_frontend_dependencies_match_lock_root():
    package = json.loads((ROOT / "package.json").read_text())
    lock = json.loads((ROOT / "package-lock.json").read_text())["packages"][""]
    assert package["devDependencies"] == lock["devDependencies"]
    assert package["engines"] == lock["engines"]
