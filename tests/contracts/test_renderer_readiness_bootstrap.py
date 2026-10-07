import hashlib
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from mira.bootstrap.character_assets import renderer_readiness
from mira.config.settings import Settings
from mira.domain.story import CapabilityState
from mira.entrypoints.http.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_static_renderer_does_not_claim_code_native_assets():
    catalog = renderer_readiness('static-pixi')
    assert {record.capability_id for record in catalog.records} == {'mira.media.trip_photo', 'cafe.scene.rain_window'}
    assert catalog.state_for('mira.pose.camera_raise') is not CapabilityState.READY


def test_selected_review_renderer_binds_software_readiness_without_art_approval():
    catalog = renderer_readiness('code-native-review')
    amber = catalog.get('mira.outfit.amber_raincoat')
    assert amber.state is CapabilityState.READY
    assert set(amber.verified_assets) == {'outer.amber', 'inner.cream'}
    assert 'software-review' in amber.evidence_id
    assert catalog.state_for('mira.emotion.guarded') is CapabilityState.READY
    assert catalog.state_for('mira.accessory.star_clip') is CapabilityState.READY
    assert catalog.state_for('mira.pose.look_at_rain') is CapabilityState.UNAVAILABLE
    path = ROOT / 'apps/web/public/scene/code-native/readiness-catalog.json'
    data = json.loads(path.read_text())
    assert data['likenessApproved'] is False
    assert set(data['sources']) == {'face', 'body', 'expression', 'hair', 'motion'}
    assert catalog.revision.endswith(hashlib.sha256(path.read_bytes()).hexdigest())
    for item in data['sources'].values():
        assert hashlib.sha256((ROOT / item['path']).read_bytes()).hexdigest() == item['sha256']


@pytest.mark.parametrize('mutation', ['unknown-status', 'wrong-renderer', 'wrong-version', 'missing-body', 'missing-hair', 'unknown-source'])
def test_invalid_catalog_cannot_announce_drawable_assets(tmp_path, mutation):
    path = ROOT / 'apps/web/public/scene/code-native/readiness-catalog.json'
    data = json.loads(path.read_text())
    if mutation == 'unknown-status': data['assets']['mira.outfit.amber_raincoat']['status'] = 'guessed'
    if mutation == 'wrong-renderer': data['renderer'] = 'other'
    if mutation == 'wrong-version': data['schemaVersion'] = True
    if mutation == 'missing-body': del data['sources']['body']
    if mutation == 'missing-hair': data['sources'].pop('hair', None)
    if mutation == 'unknown-source': data['sources']['unknown'] = data['sources']['face']
    target = tmp_path / 'public/scene/code-native/readiness-catalog.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='character_readiness_catalog_invalid'):
        renderer_readiness('code-native-review', web_root=tmp_path)


@pytest.mark.asyncio
async def test_selected_renderer_is_explicit_in_real_http_entry_and_static_catalog():
    app = create_app(settings=Settings(), character_renderer='code-native-review')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        page = await client.get('/')
        assert 'data-character-renderer="code-native-review"' in page.text
        response = await client.get('/assets/scene/code-native/readiness-catalog.json')
        assert response.status_code == 200
        assert response.json()['likenessApproved'] is False

@pytest.mark.asyncio
@pytest.mark.parametrize('renderer', ['static-pixi', 'code-native-review'])
async def test_real_application_exposes_selected_visual_readiness_without_story(renderer):
    import asyncio
    from uuid import uuid4
    from mira.application.contracts import CandidateRange, EffectProposal
    from mira.domain.models import EffectKind
    from mira.bootstrap.development_review import create_development_review_providers
    from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
    from tests.contracts.test_development_review_composition import SyntheticJevTransport
    seen=[]; generated=asyncio.Event()
    class Generation:
        async def generate(self, context):
            seen.append(context);generated.set()
            yield CandidateRange((EffectProposal(EffectKind.SUBTITLE, '先聊聊。'),), 'synthetic-ready')
    transport=SyntheticJevTransport(output_choice='allow')
    providers=create_development_review_providers(generation=Generation(),
        input_transport=transport,output_transport=transport,authorized=True,
        decision_policy=USER_DEVELOPMENT_0_6_V2,
        input_request_limit=2,output_request_limit=2,conversation_first=True)
    app=create_app(settings=Settings(),providers=providers,character_renderer=renderer)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://testserver') as client:
            created=await client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())})
            assert created.status_code==201
            body=created.json();sid=body['session']['session_id']
            response=await client.post(f'/api/v1/sessions/{sid}/inputs',
                headers={'X-Mira-Session-Token':body['session_token']},
                json={'request_id':str(uuid4()),'activity_seq':1,'presentation_cutoff':0,'text':'你好'})
            assert response.status_code==202
            await asyncio.wait_for(generated.wait(),1)
    assert seen[0].character_story is None
    assert seen[0].character_assets.state_for('mira.media.trip_photo') is CapabilityState.READY
    if renderer=='code-native-review':
        assert seen[0].character_assets.state_for('mira.pose.camera_raise') is CapabilityState.READY
    else:
        assert seen[0].character_assets.state_for('mira.pose.camera_raise') is not CapabilityState.READY
