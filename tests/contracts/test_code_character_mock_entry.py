from uuid import uuid4
import time
import asyncio

from httpx import ASGITransport, AsyncClient
import pytest

from mira.config.settings import Settings
from mira.entrypoints.http.app import create_app


@pytest.mark.parametrize('text,pose', [
    ('演示：黑夹克', 'outfit_black_jacket'),
    ('演示：奶油内搭', 'outfit_cream_inner_only'),
    ('演示：琥珀雨衣', 'outfit_amber_raincoat'),
    ('演示：平常', 'emotion_normal'),
    ('演示：戒备', 'emotion_guarded'),
    ('演示：开心', 'emotion_happy'),
    ('演示：娇羞', 'emotion_shy'),
    ('演示：相机头饰', 'accessory_camera_clip'),
    ('演示：银星发卡', 'accessory_star_clip'),
])
@pytest.mark.asyncio
async def test_explicit_code_mock_command_reaches_actor_grant_and_exact_receipt(text, pose):
    app = create_app(Settings(), character_renderer='code-native-review')
    async with app.router.lifespan_context(app), AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        created = (await client.post('/api/v1/sessions', json={'client_instance_id':str(uuid4())})).json()
        path = '/api/v1/sessions/' + created['session']['session_id']
        headers = {'X-Mira-Session-Token':created['session_token']}
        assert (await client.post(path + '/inputs', headers=headers, json={
            'request_id':str(uuid4()), 'activity_seq':1, 'presentation_cutoff':0, 'text':text})).status_code == 202
        until = time.monotonic() + 3
        while time.monotonic() < until:
            view = (await client.get(path, headers=headers)).json()
            if view['sealed']:break
            await asyncio.sleep(.005)
        effects = view['active_grants']
        assert any(item['kind']=='pose' and item['value']==pose for item in effects)
        assert view['presented_effects'] == []
        for index, effect in enumerate(effects, 1):
            response = await client.post(path + '/receipts', headers=headers, json={
                'effect_id':effect['id'], 'digest':effect['digest'], 'activity_seq':1,
                'output_epoch':view['output_epoch'], 'presentation_seq':index})
            assert response.status_code == 200
        assert any(item['value']==pose for item in response.json()['presented_effects'])
        capability = (await client.get('/api/v1/voice-capabilities')).json()
        assert capability['generation_mode'] == 'mock'
        assert not capability['microphone_enabled'] and not capability['speech_enabled']


@pytest.mark.asyncio
async def test_generic_mock_and_near_match_do_not_gain_the_explicit_review_commands():
    from mira.adapters.generation.mock import MockGenerationBackend
    from mira.application.contracts import GenerationContext
    from mira.domain.models import EffectKind
    for backend,text in [(MockGenerationBackend(0),'演示：琥珀雨衣'),
                         (MockGenerationBackend(0,character_review=True),'演示：琥珀雨衣extra')]:
        context=GenerationContext(text,(),(),1)
        result=[part async for part in backend.generate(context)]
        assert all(effect.kind is not EffectKind.POSE for part in result for effect in part.effects)
