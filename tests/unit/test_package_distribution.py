"""Cheap packaging policy tests; the real build/install smoke belongs to package lane."""
import runpy
import sys
import tomllib
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_local_memory_console_assets_are_declared():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    data = config["tool"]["setuptools"]["data-files"]
    assert "apps/web/local-memory.html" in data["apps/web"]
    assert "apps/web/public/*.css" in data["apps/web/public"]
    assert "apps/web/dist/local-memory/*.js" in data["apps/web/dist/local-memory"]
    setup = (ROOT / "setup.py").read_text()
    assert 'web / "local-memory.html"' in setup
    assert 'web / "dist/local-memory/main.js"' in setup


def test_declared_install_data_contains_config_and_built_workbench():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    data = config["tool"]["setuptools"].get("data-files", {})
    assert "config/defaults.toml" in data.get("config", [])
    assert "apps/web/index.html" in data.get("apps/web", [])
    assert "apps/web/local-memory.html" in data.get("apps/web", [])
    assert "apps/web/dist/local-memory" in data
    for folder in ("public", "public/audio", "public/scene", "dist/app", "dist/local-memory",
                   "dist/features/audio", "dist/features/diagnostics",
                   "dist/features/session", "dist/features/presentation",
                   "dist/shared", "dist/shared/generated"):
        assert "apps/web/" + folder in data, folder
    assert "apps/web/public/scene/*.png" in data["apps/web/public/scene"], (
        "versioned scene background plates must travel with the installed web assets"
    )
    from tools.verify_package import resource_manifest
    assert "apps/web/public/scene/cafe-painterly-lighting-v3-table-free.png" in resource_manifest(ROOT)


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


def test_package_source_staging_excludes_root_dotenv_and_build_marker_only(tmp_path):
    from tools.verify_package import resource_manifest, stage_source

    source = tmp_path / "synthetic"
    for name in ("apps/api/src", "apps/web/src", "apps/web/public", "apps/web/dist/app", "config"):
        (source / name).mkdir(parents=True)
    for name in ("pyproject.toml", "setup.py", "apps/web/index.html", "apps/web/local-memory.html",
                 "apps/web/tsconfig.json",
                 "config/defaults.toml"):
        (source / name).write_text("synthetic")
    (source / ".env").write_text("synthetic-private-do-not-copy")
    (source / "config/.env").write_text("synthetic-private-do-not-copy")
    asset = source / "apps/web/dist/app/main.js"
    asset.write_bytes(b"export const synthetic = true;\n")
    internal_marker = source / "apps/web/dist/.mira-web-build-output"
    internal_marker.write_text("mira-web-build-output:v1\n")
    nested_marker = source / "apps/web/dist/app/.mira-web-build-output"
    nested_marker.write_bytes(b"nested file is a runtime resource\n")
    staged = tmp_path / "staged"
    stage_source(staged, root=source)
    assert not (staged / ".env").exists()
    assert not (staged / "config/.env").exists()
    assert (staged / "config/defaults.toml").read_text() == "synthetic"
    assert not (staged / "apps/web/dist/.mira-web-build-output").exists()
    assert (staged / "apps/web/dist/app/main.js").read_bytes() == asset.read_bytes()
    assert (staged / "apps/web/dist/app/.mira-web-build-output").read_bytes() == nested_marker.read_bytes()
    manifest = resource_manifest(staged)
    assert "apps/web/dist/.mira-web-build-output" not in manifest
    assert manifest["apps/web/dist/app/main.js"]
    assert manifest["apps/web/dist/app/.mira-web-build-output"]


def test_offline_builder_respects_declared_exact_build_requirements(monkeypatch, tmp_path):
    from tools import verify_package
    from tools.dev import StartupError

    (tmp_path / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools==999.0.0", "wheel==0.48.0"]\n')
    monkeypatch.setattr(verify_package, "ROOT", tmp_path)
    with pytest.raises(StartupError, match="build"):
        verify_package.check_builder(sys.executable)


def test_release_local_package_lane_provisions_declared_web_compiler():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    release_job = workflow.split("  release-local:", 1)[1]
    assert "uses: actions/setup-node@v4" in release_job
    assert "node-version: '22.16.0'" in release_job
    assert "run: npm ci --ignore-scripts" in release_job
    assert release_job.index("run: npm ci --ignore-scripts") < release_job.index(
        "python tools/check.py --lane package smoke"
    )
