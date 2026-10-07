"""Bind the selected renderer to exact shipped sources and the authored photo.

READY means implemented software, never approved likeness or a presentation.
The browser still prepares, renders and acknowledges completion independently.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from mira.config.loader import project_root
from mira.domain.story import CapabilityRecord, CapabilityState, ReadinessCatalog
from mira.domain.xiahe_chapter import CHAPTER_CAPABILITIES, CHAPTER_ASSETS, CHAPTER_REVISION

_SOURCES = {'face': 'character.js', 'body': 'body.js',
            'expression': 'expression.js', 'hair': 'hair.js', 'motion': 'camera-motion.js'}
_SOURCE_BASE = 'apps/web/src/features/presentation/code-native-vendor/'
_RENDERER_PATH = 'apps/web/src/features/presentation/code-native-character-renderer.ts'
_PHOTO_PATH = 'public/scene/trip-memory.svg'
_PHOTO_SHA256 = 'e6571c45bb27bcc010854ffed0077837a225959d8224437b2b6234a5b0d8745e'

_CHAPTER_SOURCES = {
    'apps/web/index.html': '9698e0be39e2ea31e40a3dd974b6fbdb053f9f455ed98aa46122fdebdc4db321',
    'apps/web/public/chapter-presentation.css': '93b94807e0cb13efb36e84644389ad033bb20778ae6e32afc56857cd8a7933d1',
    'apps/web/src/features/presentation/chapter-presentation.ts': '2f4ecea34aa0aec307ca1e48d978dbce225e08c26783487a9bb7ff143bb94808',
    'apps/web/src/features/presentation/scene-executor.ts': '5db58662ef14131e2cbfc52e3cc3c27d01b5e278605ff126988d0995e4122d01',
    'apps/web/src/features/session/controller.ts': '69b839c2cb6b749140cf46c9ca9eb5d00e6553df09787f45fc3a2d08d66faa56',
    'apps/web/src/shared/protocol.ts': '90fec7d7ce149415658914687a1c338e3dfc72a282b52f8bd6dfe7c535d3f8c1',
    'apps/web/src/app/main.ts': 'c28e2a1b5cf9051ed84e48db2533f7d508e493573a2911659d13c86ca1526c2e',
}


def _chapter_records(root: Path, *, renderer_ready: bool, photo: CapabilityRecord):
    ready = renderer_ready and photo.state is CapabilityState.READY and all(
        _verified_source(root, {'path': name, 'sha256': digest}, name)
        for name, digest in _CHAPTER_SOURCES.items())
    attestation = 'chapter-composition:' + hashlib.sha256(
        json.dumps(_CHAPTER_SOURCES, sort_keys=True).encode()).hexdigest()
    return tuple(CapabilityRecord(capability, CapabilityState.READY if ready else CapabilityState.UNAVAILABLE,
        CHAPTER_REVISION if ready else None, (CHAPTER_ASSETS[scene],) if ready else (),
        attestation if ready else None) for scene, capability in CHAPTER_CAPABILITIES.items())


def _verified_source(root: Path, item, expected_path: str) -> bool:
    if (type(item) is not dict or item.get('path') != expected_path
            or type(item.get('sha256')) is not str
            or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
        return False
    path = root / expected_path.removeprefix('apps/web/')
    try:
        if not path.resolve().is_relative_to(root.resolve()):
            return False
        raw = path.read_bytes()
        return len(raw) <= 262144 and hashlib.sha256(raw).hexdigest() == item['sha256']
    except OSError:
        return False


def _photo_record(root: Path) -> CapabilityRecord:
    try:
        path = root / _PHOTO_PATH
        raw = path.read_bytes() if path.resolve().is_relative_to(root.resolve()) else b''
        ready = len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == _PHOTO_SHA256
    except OSError:
        ready = False
    return CapabilityRecord('mira.media.trip_photo',
        CapabilityState.READY if ready else CapabilityState.UNAVAILABLE,
        'authored-illustration:' + _PHOTO_SHA256 if ready else None,
        ('authored.local.trip_photo',) if ready else (),
        'sha256:' + _PHOTO_SHA256 if ready else None)


_SCENE_SOURCES = {'public/scene/cafe-night.svg': '3c3dcfb31b9126ab3ee511dd1e241fd2d714babcfd100651346fd162913cbf96', 'public/scene/cafe-painterly-lighting-v3-table-free.png': '4bd221f284181946d9427fd7fab042fba7e56ff8014046c577f0d60fea389fb3', 'public/scene-view.css': '6d693d0c313165b58fbd21b7eecbc540fccacd5b031140d8cebf69f20e7fe72f'}

def _scene_record(root: Path) -> CapabilityRecord:
    ready = True
    for name, digest in _SCENE_SOURCES.items():
        try:
            path = root / name
            raw = path.read_bytes() if path.resolve().is_relative_to(root.resolve()) else b''
            ready = ready and len(raw) <= 8 * 1024 * 1024 and hashlib.sha256(raw).hexdigest() == digest
        except OSError:
            ready = False
    revision = 'window-view:' + hashlib.sha256(json.dumps(_SCENE_SOURCES, sort_keys=True).encode()).hexdigest()
    return CapabilityRecord('cafe.scene.rain_window',
        CapabilityState.READY if ready else CapabilityState.UNAVAILABLE,
        revision if ready else None, ('scene.rain_window.composition',) if ready else (),
        revision if ready else None)


def renderer_readiness(renderer: str, *, web_root: Path | None = None) -> ReadinessCatalog:
    root = web_root if web_root is not None else project_root() / 'apps/web'
    photo = _photo_record(root)
    scene = _scene_record(root)
    if renderer == 'static-pixi':
        return ReadinessCatalog('mira-static-authored-photo-v1', (photo, scene))
    if renderer != 'code-native-review':
        raise ValueError('character_renderer_invalid')
    try:
        raw = (root / 'public/scene/code-native/readiness-catalog.json').read_bytes()
        if len(raw) > 32768:
            raise ValueError('size')
        data = json.loads(raw)
        if (type(data['schemaVersion']) is not int or data['schemaVersion'] != 1
                or data['renderer'] != renderer or data['visualAcceptance'] != 'pending'
                or data['likenessApproved'] is not False):
            raise ValueError('schema')
        sources = data['sources']
        if type(sources) is not dict or set(sources) not in (set(_SOURCES), set(_SOURCES)-{'motion'}):
            raise ValueError('sources')
        for key, source in sources.items():
            if not _verified_source(root, source, _SOURCE_BASE + _SOURCES[key]):
                raise ValueError('source revision')
        # A new capability label alone is insufficient. It binds the source set
        # and the actual renderer that drives and completes that source's motion.
        motion_ready = ('motion' in sources
            and data.get('capabilities', {}).get('cameraMotion') is True
            and _verified_source(root, data.get('rendererSource'), _RENDERER_PATH))
        revision = 'code-native-review:' + hashlib.sha256(raw).hexdigest()
        records = []
        assets = data['assets']
        if not isinstance(assets, dict) or not 1 <= len(assets) <= 63:
            raise ValueError('assets')
        for identifier, item in assets.items():
            if not re.fullmatch(r'mira\.(outfit|emotion|accessory|pose|face|phase)\.[a-z_]+', identifier):
                raise ValueError('asset ID')
            if item['status'] not in ('review_only', 'unavailable'):
                raise ValueError('asset status')
            ready = item['status'] == 'review_only'
            if identifier == 'mira.pose.camera_raise':
                ready = ready and motion_ready
            parts = ('outer.amber', 'inner.cream') if identifier == 'mira.outfit.amber_raincoat' else (identifier,)
            records.append(CapabilityRecord(identifier,
                CapabilityState.READY if ready else CapabilityState.UNAVAILABLE,
                revision if ready else None, parts if ready else (),
                'software-review:' + hashlib.sha256(raw).hexdigest() if ready else None))
        chapter = _chapter_records(root, renderer_ready=(
            _verified_source(root, data.get('rendererSource'), _RENDERER_PATH)
            and any(record.capability_id == 'mira.emotion.happy' and record.state is CapabilityState.READY
                    for record in records)), photo=photo)
        return ReadinessCatalog(revision, tuple(records) + (photo, scene) + chapter)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ValueError('character_readiness_catalog_invalid') from None
