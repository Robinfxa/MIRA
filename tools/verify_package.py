"""Build/install a wheel offline in a temporary copy and smoke its API and web assets.

The calling Python supplies runtime/test dependencies. --build-python can select
an existing pip/setuptools/wheel environment; nothing is downloaded or installed
into either interpreter. Only the finished wheel is installed into a temp target.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.dev import StartupError, child_environment, compiler_command


def stage_source(destination: Path, *, root: Path = ROOT) -> None:
    destination.mkdir()
    for name in ("pyproject.toml", "setup.py"):
        shutil.copy2(root / name, destination / name)
    shutil.copytree(root / "apps/api/src", destination / "apps/api/src",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
    # Copy public reviewed configuration only, never dotenv or a root-wide tree.
    for path in (root / "config").rglob("*.toml"):
        target = destination / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    web = destination / "apps/web"
    web.mkdir(parents=True)
    for name in ("index.html", "tsconfig.json"):
        shutil.copy2(root / "apps/web" / name, web / name)
    shutil.copytree(root / "apps/web/src", web / "src")
    shutil.copytree(root / "apps/web/public", web / "public")


def resource_manifest(source: Path) -> dict[str, str]:
    resources = [source / "apps/web/index.html"]
    for relative in ("config", "apps/web/public", "apps/web/dist"):
        resources.extend(path for path in (source / relative).rglob("*") if path.is_file())
    return {path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(resources)}


def verify_installed_files(installed: Path, manifest: dict[str, str]) -> None:
    for relative, digest in manifest.items():
        path = installed / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Wheel missing or changed installed resource: {relative}")


def check_builder(python: str) -> None:
    with (ROOT / "pyproject.toml").open("rb") as file:
        requirements = tomllib.load(file)["build-system"]["requires"]
    code = """import json, sys
from importlib.metadata import version
assert (3, 11) <= sys.version_info[:2] < (3, 14)
for requirement in json.loads(sys.argv[1]):
    name, expected = requirement.split('==')
    assert version(name) == expected, 'build dependency does not match pyproject pin'
for name in ('pip', 'setuptools', 'wheel'):
    print(name + '=' + version(name))
"""
    try:
        result = subprocess.run([python, "-I", "-c", code, json.dumps(requirements)], capture_output=True, text=True,
                                timeout=15, env=child_environment())
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is None or result.returncode:
        raise StartupError("Package build needs existing pip and the exact pyproject build requirements on Python "
                           "3.11–3.13; select that interpreter with --build-python PATH. No install attempted.")
    print(f"Build interpreter: {python}; {result.stdout.strip()}", flush=True)


INSTALLED_SMOKE = r'''
import hashlib, json, sys
from pathlib import Path
from uuid import uuid4
installed = Path(sys.argv[1]).resolve()
manifest = json.loads(Path(sys.argv[2]).read_text())
sys.path.insert(0, str(installed))
import mira
from mira.config.loader import load_settings, project_root
from mira.adapters.generation.replay.script import load_script
from mira.entrypoints.http.app import create_app
from fastapi.testclient import TestClient
assert Path(mira.__file__).resolve().is_relative_to(installed)
assert project_root() == installed, 'checkout must not supply configuration or assets'
assert len(load_script('photo-tour').steps) == 2
assert load_script('failed-tail').finish == 'fail'
assert len(load_script('delayed-photo').steps) == 2
settings = load_settings(environ={'MIRA_PROFILE': 'mock'}, overrides={
    'diagnostics': {'enabled': False}, 'providers': {'mock_delay_ms': 0}})
assert settings.providers.generation == 'mock'
assert not settings.providers.allow_external_calls and not settings.providers.allow_paid_api
served = 0
with TestClient(create_app(settings)) as client:
    health = client.get('/api/v1/health')
    assert health.status_code == 200 and health.json()['mode'] == 'mock'
    assert health.json()['live_llm'] is False and health.json()['live_audio'] is False
    for relative, digest in manifest.items():
        if relative == 'apps/web/index.html':
            url = '/'
        elif relative.startswith('apps/web/public/'):
            url = '/assets/' + relative.removeprefix('apps/web/public/')
        elif relative.startswith('apps/web/dist/'):
            url = '/dist/' + relative.removeprefix('apps/web/dist/')
        else:
            continue
        response = client.get(url)
        assert response.status_code == 200, url
        assert hashlib.sha256(response.content).hexdigest() == digest, url
        served += 1
    response = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())})
    assert response.status_code == 201
    session = response.json()
    session_id = session['session']['session_id']
    headers = {'X-Mira-Session-Token': session['session_token']}
    assert client.get('/api/v1/sessions/' + session_id, headers=headers).status_code == 200
    assert client.delete('/api/v1/sessions/' + session_id, headers=headers).status_code == 204
    for url in ('/.env', '/config/defaults.toml', '/pyproject.toml'):
        assert client.get(url).status_code == 404, url
# Explicit rehearsal must carry its private package PCM, never borrow checkout files.
from mira.adapters.generation.rehearsal.backend import load_clips
clips = load_clips()
assert len(clips) == 8 and all(clip.pcm for clip in clips.values())
rehearsal = load_settings(environ={'MIRA_PROFILE': 'rehearsal'}, overrides={
    'diagnostics': {'enabled': False}, 'providers': {'mock_delay_ms': 0}})
with TestClient(create_app(rehearsal)) as client:
    caps = client.get('/api/v1/voice-capabilities').json()
    assert caps['generation_mode'] == 'rehearsal' and caps['qualification'] == 'offline_fixture'
    assert caps['speech_enabled'] is True and caps['microphone_enabled'] is False
    assert client.get('/api/v1/health').json()['live_audio'] is False
    assert client.get('/assets/audio/offline-rehearsal-v1/manifest.json').status_code == 404
print('Installed rehearsal smoke passed: eight integrity-checked package clips, explicit offline '
      'capabilities, live audio false and microphone disabled.')
print(f'Installed-wheel smoke passed: {served} exact web resources, config, 3 replay fixtures, '
      'health, session create/read/delete and private-path rejection. Runtime Python ' + sys.version.split()[0])
print('Offline ASGI/package check only; no live providers, real audio, browser or device claim.')
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-python", default=sys.executable,
                        help="existing Python with pip/setuptools/wheel; runtime uses the calling Python")
    args = parser.parse_args()
    try:
        check_builder(args.build_python)
        compiler = compiler_command()
        env = child_environment()
        with tempfile.TemporaryDirectory(prefix="mira-wheel-check-") as temporary:
            root = Path(temporary)
            source, wheels, installed = root / "source", root / "wheels", root / "installed"
            stage_source(source)
            subprocess.run([*compiler, "-p", str(source / "apps/web/tsconfig.json"),
                            "--sourceMap", "false"], cwd=root, env=env, check=True, timeout=90)
            manifest = resource_manifest(source)
            manifest_path = root / "resources.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            subprocess.run([args.build_python, "-I", "-m", "pip", "--isolated",
                            "--disable-pip-version-check", "--no-cache-dir", "wheel", str(source), "--no-deps",
                            "--no-build-isolation", "--no-index", "--wheel-dir", str(wheels)],
                           cwd=root, env=env, check=True, timeout=90)
            wheel, = wheels.glob("*.whl")
            subprocess.run([args.build_python, "-I", "-m", "pip", "--isolated",
                            "--disable-pip-version-check", "--no-cache-dir", "install", "--no-index", "--no-deps",
                            "--no-compile", "--target", str(installed), str(wheel)],
                           cwd=root, env=env, check=True, timeout=60)
            verify_installed_files(installed, manifest)
            subprocess.run([sys.executable, "-I", "-c", INSTALLED_SMOKE,
                            str(installed), str(manifest_path)],
                           cwd=root, env=env, check=True, timeout=30)
            print(f"Wheel {wheel.name}: sha256={hashlib.sha256(wheel.read_bytes()).hexdigest()}; "
                  f"{len(manifest)} installed config/web resources verified.")
        return 0
    except (StartupError, RuntimeError) as error:
        print(f"Package check failed: {error}", file=sys.stderr)
        return 2
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("Package check failed or timed out; see preceding build/install/smoke output.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
