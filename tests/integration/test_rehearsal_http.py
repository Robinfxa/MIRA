"""DEMO01-004: real Actor/permit/cue/authenticated speech with authored offline PCM."""
import base64
import json
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.config.loader import ConfigurationError, load_settings
from mira.entrypoints.http.app import create_app

ROOT = Path(__file__).resolve().parents[2]


def settings():
    return load_settings(root=ROOT, environ={"MIRA_PROFILE": "rehearsal"},
                         overrides={"providers": {"mock_delay_ms": 0}})


def wait(client, path, headers):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        state = client.get(path, headers=headers).json()
        if state["sealed"]:
            return state
        time.sleep(.005)
    pytest.fail("rehearsal did not seal")


def test_profile_caps_audio_cue_stop_and_followup_through_existing_actor():
    with TestClient(create_app(settings())) as client:
        caps = client.get('/api/v1/voice-capabilities').json()
        assert caps["generation_mode"] == "rehearsal" and caps["qualification"] == "offline_fixture"
        assert caps["speech_enabled"] is True and caps["microphone_enabled"] is False
        health = client.get('/api/v1/health').json()
        assert health["mode"] == "rehearsal" and health["live_audio"] is False and health["live_llm"] is False
        assert client.get('/api/v1/diagnostics-status').json()["recording_active"] is False
        created = client.post('/api/v1/sessions', json={"client_instance_id": str(uuid4())}).json()
        path = '/api/v1/sessions/' + created['session']['session_id']
        headers = {'X-Mira-Session-Token': created['session_token']}
        assert client.post(path + '/inputs', headers=headers, json={"request_id": str(uuid4()),
            "activity_seq": 1, "presentation_cutoff": 0, "text": "看照片"}).status_code == 202
        state = wait(client, path, headers)
        speech = next(e for e in state['active_grants'] if e['kind'] == 'speech')
        photo = next(e for e in state['active_grants'] if e['kind'] == 'media')
        caption = next(e for e in state['active_grants'] if e['kind'] == 'subtitle')
        assert caption['cue_speech_id'] == speech['id'] and caption['cue_id'] == speech['cue_id']
        assert photo['value'] == 'trip_photo'
        origin = {k: speech[k] for k in ('digest', 'output_epoch', 'activity_seq')}
        response = client.post(path + '/speech/' + speech['id'] + '/stream', headers=headers, json=origin)
        assert response.status_code == 200
        frames = [json.loads(line) for line in response.text.splitlines()]
        assert frames[-1]['type'] == 'complete' and frames[-1]['total_samples'] > 24000
        audio = frames[:-1]
        assert all(frame['type'] == 'audio' and len(base64.b64decode(frame['pcm_base64'])) <= 12000 for frame in audio)
        assert any(any(base64.b64decode(frame['pcm_base64'])) for frame in audio)
        receipt = {"effect_id": photo['id'], "presentation_seq": 1, **{k: photo[k] for k in ('digest', 'output_epoch', 'activity_seq')}}
        assert client.post(path + '/receipts', headers=headers, json=receipt).status_code == 200
        stopped = client.post(path + '/stop', headers=headers, json={"activity_seq": 2, "presentation_cutoff": 1}).json()
        assert any(e['id'] == photo['id'] for e in stopped['presented_effects'])
        assert client.post(path + '/speech/' + speech['id'] + '/stream', headers=headers, json=origin).status_code == 409
        client.post(path + '/inputs', headers=headers, json={"request_id": str(uuid4()),
            "activity_seq": 3, "presentation_cutoff": 1, "text": "照片里有什么"})
        after = wait(client, path, headers)
        assert any('The picture is still here' in e['value'] for e in after['active_grants'])


def test_rehearsal_rejects_media_injection_that_would_mislabel_live_capability():
    with pytest.raises(ConfigurationError):
        create_app(settings(), speech_recognition=object())
    with pytest.raises(ConfigurationError):
        create_app(settings(), speech_synthesis=object())
