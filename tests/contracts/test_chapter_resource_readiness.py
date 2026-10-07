from pathlib import Path
import shutil
import tomllib

import pytest

from mira.bootstrap.character_assets import renderer_readiness, _CHAPTER_SOURCES
from mira.domain.story import CapabilityState
from mira.domain.xiahe_chapter import CHAPTER_CAPABILITIES

ROOT = Path(__file__).resolve().parents[2]


def test_chapter_composition_ready_requires_current_code_renderer_and_known_photo():
    current = renderer_readiness('code-native-review')
    fallback = renderer_readiness('static-pixi')
    for capability in CHAPTER_CAPABILITIES.values():
        assert current.state_for(capability) is CapabilityState.READY
        assert fallback.state_for(capability) is not CapabilityState.READY
    assert current.state_for('mira.media.trip_photo') is CapabilityState.READY
    assert current.state_for('mira.pose.camera_raise') is CapabilityState.READY


@pytest.mark.parametrize('missing', ['public/chapter-presentation.css',
    'src/features/presentation/chapter-presentation.ts', 'src/features/session/controller.ts'])
def test_missing_or_changed_chapter_surface_does_not_disable_previously_working_photo(tmp_path, missing):
    # Copy only capability-verification inputs, never dependency/build/private trees.
    web = ROOT / 'apps/web'
    paths = {name.removeprefix('apps/web/') for name in _CHAPTER_SOURCES}
    paths.update({'public/scene/code-native/readiness-catalog.json', 'public/scene/trip-memory.svg',
                  'src/features/presentation/code-native-character-renderer.ts'})
    paths.update(str(path.relative_to(web)) for path in
                 (web/'src/features/presentation/code-native-vendor').glob('*.js'))
    for name in paths:
        if name == missing:
            continue
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(web / name, target)
    current = renderer_readiness('code-native-review', web_root=tmp_path)
    assert current.state_for('mira.media.trip_photo') is CapabilityState.READY
    assert all(current.state_for(capability) is CapabilityState.UNAVAILABLE
               for capability in CHAPTER_CAPABILITIES.values())


def test_wheel_declares_the_same_private_source_pins_as_checkout():
    config = tomllib.loads((ROOT/'pyproject.toml').read_text())
    files = config['tool']['setuptools']['data-files']
    for name in _CHAPTER_SOURCES:
        path = Path(name)
        declared = files[path.parent.as_posix()]
        assert any(path.match(pattern) or name == pattern for pattern in declared), name
