"""Cheap packaging policy tests; the real build/install smoke belongs to package lane."""
import runpy
import sys
import tomllib
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_declared_install_data_contains_config_and_built_workbench():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    data = config["tool"]["setuptools"].get("data-files", {})
    assert "config/defaults.toml" in data.get("config", [])
    assert "apps/web/index.html" in data.get("apps/web", [])
    for folder in ("public", "public/audio", "public/scene", "dist/app",
                   "dist/features/audio", "dist/features/diagnostics",
                   "dist/features/session", "dist/features/presentation",
                   "dist/shared", "dist/shared/generated"):
        assert "apps/web/" + folder in data, folder


def test_wheel_build_fails_loudly_when_javascript_was_not_built(monkeypatch, tmp_path):
    hook = ROOT / "setup.py"
    assert hook.is_file(), "A wheel must reject missing compiled web assets rather than omit them."
    registered = {}
    setuptools = types.ModuleType("setuptools")
    setuptools.setup = lambda **kwargs: registered.update(kwargs)
    command = types.ModuleType("setuptools.command.build_py")
    command.build_py = type("BuildPy", (), {"run": lambda self: None})
    monkeypatch.setitem(sys.modules, "setuptools", setuptools)
    monkeypatch.setitem(sys.modules, "setuptools.command.build_py", command)
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(hook))
    with pytest.raises(RuntimeError, match="build"):
        registered["cmdclass"]["build_py"]().run()


def test_installed_manifest_detects_omitted_or_corrupted_assets(tmp_path):
    from tools.verify_package import resource_manifest, verify_installed_files

    source, installed = tmp_path / "source", tmp_path / "installed"
    asset = source / "apps/web/index.html"
    asset.parent.mkdir(parents=True)
    asset.write_text("synthetic public HTML")
    manifest = resource_manifest(source)
    with pytest.raises(RuntimeError, match="apps/web/index.html"):
        verify_installed_files(installed, manifest)
    target = installed / "apps/web/index.html"
    target.parent.mkdir(parents=True)
    target.write_text("wrong asset")
    with pytest.raises(RuntimeError, match="apps/web/index.html"):
        verify_installed_files(installed, manifest)
    target.write_bytes(asset.read_bytes())
    verify_installed_files(installed, manifest)


def test_package_source_staging_excludes_root_dotenv(tmp_path):
    from tools.verify_package import stage_source

    source = tmp_path / "synthetic"
    for name in ("apps/api/src", "apps/web/src", "apps/web/public", "config"):
        (source / name).mkdir(parents=True)
    for name in ("pyproject.toml", "setup.py", "apps/web/index.html", "apps/web/tsconfig.json",
                 "config/defaults.toml"):
        (source / name).write_text("synthetic")
    (source / ".env").write_text("synthetic-private-do-not-copy")
    (source / "config/.env").write_text("synthetic-private-do-not-copy")
    staged = tmp_path / "staged"
    stage_source(staged, root=source)
    assert not (staged / ".env").exists()
    assert not (staged / "config/.env").exists()
    assert (staged / "config/defaults.toml").read_text() == "synthetic"


def test_offline_builder_respects_declared_exact_build_requirements(monkeypatch, tmp_path):
    from tools import verify_package
    from tools.dev import StartupError

    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools==999.0.0", "wheel==0.48.0"]\n')
    monkeypatch.setattr(verify_package, "ROOT", tmp_path)
    with pytest.raises(StartupError, match="build"):
        verify_package.check_builder(sys.executable)
