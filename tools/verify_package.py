"""Build/install a wheel offline in a temporary copy and smoke its API and web assets.

The calling Python supplies runtime/test dependencies. --build-python can select
an existing pip/setuptools/wheel environment; nothing is downloaded or installed
into either interpreter. Only the finished wheel is installed into a temp target.
"""
import argparse
from contextlib import nullcontext
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_BUILD_OUTPUT_MARKER = '.mira-web-build-output'
sys.path.insert(0, str(ROOT))
from tools.dev import StartupError, child_environment, web_build_command


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
    for name in ("index.html", "local-memory.html", "tsconfig.json"):
        shutil.copy2(root / "apps/web" / name, web / name)
    shutil.copytree(root / "apps/web/src", web / "src")
    shutil.copytree(root / "apps/web/public", web / "public")
    source_dist = root / "apps/web/dist"

    def ignore_root_build_marker(directory: str, names: list[str]) -> set[str]:
        if Path(directory).resolve() == source_dist.resolve():
            return {WEB_BUILD_OUTPUT_MARKER} & set(names)
        return set()

    shutil.copytree(source_dist, web / "dist", ignore=ignore_root_build_marker)


def resource_manifest(source: Path) -> dict[str, str]:
    resources = [source / "apps/web/index.html"]
    local_page = source / "apps/web/local-memory.html"
    if local_page.is_file():
        resources.append(local_page)
    for relative in ("config", "apps/web/public", "apps/web/dist"):
        resources.extend(path for path in (source / relative).rglob("*") if path.is_file())
    # The code-native readiness contract binds the five authored source modules
    # and its renderer. Installed applications need the same public evidence.
    resources.extend((source / "apps/web/src/features/presentation/code-native-vendor").glob("*.js"))
    renderer_source = source / "apps/web/src/features/presentation/code-native-character-renderer.ts"
    if renderer_source.is_file():
        resources.append(renderer_source)
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
        if relative in {'apps/web/local-memory.html', 'apps/web/public/local-memory.css',
                        'apps/web/dist/local-memory/main.js'}:
            continue
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
# The selected native renderer also works in a wheel, without borrowing checkout sources.
from mira.bootstrap.character_assets import renderer_readiness
from mira.domain.story import CapabilityState
native = renderer_readiness('code-native-review', web_root=installed / 'apps/web')
assert native.state_for('mira.pose.camera_raise') is CapabilityState.READY
assert native.state_for('mira.media.trip_photo') is CapabilityState.READY
with TestClient(create_app(settings, character_renderer='code-native-review',
                           web_root=installed / 'apps/web')) as client:
    assert client.get('/api/v1/health').status_code == 200
    assert 'data-character-renderer="code-native-review"' in client.get('/').text
    assert client.get('/src/features/presentation/code-native-character-renderer.ts').status_code == 404
# The separate local console serves only its exact page resources and APIs.
from mira.entrypoints.http.local_memory_app import create_local_memory_app
from mira.entrypoints.http.operator_pairing import OperatorPairing
async def unexpected_factory():
    raise AssertionError('local store opened before a successful pairing')
with TestClient(create_local_memory_app(
        management_factory=unexpected_factory,
        pairing=OperatorPairing('synthetic-package-pairing-code-0123456789',
                                ('http://127.0.0.1:8761',)),
        web_root=installed / 'apps/web')) as client:
    headers = {'Host': '127.0.0.1:8761'}
    health = client.get('/health', headers=headers)
    assert health.status_code == 200
    assert health.json() == {'status': 'ok', 'mode': 'local-memory-management',
                              'provider_transmission': False}
    for relative, url in (
        ('apps/web/local-memory.html', '/'),
        ('apps/web/public/local-memory.css', '/local-memory.css'),
        ('apps/web/dist/local-memory/main.js', '/local-memory.js'),
    ):
        response = client.get(url, headers=headers)
        assert response.status_code == 200, url
        assert hashlib.sha256(response.content).hexdigest() == manifest[relative], url
        served += 1
    page = client.get('/', headers=headers).text
    assert 'name="message"' not in page
    assert 'data-local-only-notice' in page
    assert '不会向外部服务传送记忆内容' in page
    assert client.get('/api/v1/memory-management/status', headers=headers).status_code == 401
    assert client.get('/api/v1/sessions', headers=headers).status_code == 404
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
    parser.add_argument("--output-dir", type=Path,
                        help="new directory preserving source, wheel and installed smoke evidence")
    args = parser.parse_args()
    try:
        check_builder(args.build_python)
        env = child_environment()
        subprocess.run(web_build_command(), cwd=ROOT, env=env, check=True, timeout=120)
        if args.output_dir is not None:
            args.output_dir.mkdir(parents=True, exist_ok=False)
        evidence = (nullcontext(str(args.output_dir.resolve())) if args.output_dir is not None
                    else tempfile.TemporaryDirectory(prefix="mira-wheel-check-"))
        with evidence as temporary:
            root = Path(temporary)
            source, wheels, installed = root / "source", root / "wheels", root / "installed"
            stage_source(source)
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
