from dataclasses import asdict, replace
from uuid import uuid4

import pytest

from mira.domain.models import SessionState
from mira.entrypoints.http.mappers import session_view


def projection(**changes):
    value = dict(schema='mira.xiahe-chapter.v1', source_hash='a' * 64,
        stage='gift_offered', role_active=True, role_name='夏禾',
        active_gift_offer_id='offer-one', gift_offer_effect_id=str(uuid4()),
        gift_offer_effect_digest='b' * 64, pending_transition=None,
        completed=False, revision=7, suspended=False)
    value.update(changes)
    return value


def test_legacy_no_story_session_has_no_role_or_offer():
    wire = session_view(SessionState('session', 'client')).model_dump(mode='json')
    assert wire['chapter_projection'] is None


def test_public_chapter_snapshot_excludes_authored_text_and_internal_scope():
    from mira.domain.chapter_presentation import chapter_presentation
    data = projection(authored_canon=[{'text': 'private synthetic test text'}],
                      role_scope='internal scope', allowed_next=['x.gift_accept'])
    public = chapter_presentation(data)
    wire = session_view(replace(SessionState('session', 'client'), chapter_projection=public))
    # FastAPI serializes response models with aliases, including the schema key.
    dumped = wire.model_dump(mode='json', by_alias=True)['chapter_projection']
    assert dumped == {key: data[key] for key in asdict(public)}
    assert 'private synthetic test text' not in wire.model_dump_json()


@pytest.mark.parametrize('key,value', [
    ('stage', 'npc_arrived'), ('role_name', 'another person'),
    ('source_hash', 'unbounded-secret'), ('pending_transition', 'run_shell'),
    ('gift_offer_effect_digest', 'secret'), ('role_active', 'true'),
    ('revision', True), ('revision', -1), ('active_gift_offer_id', 'x' * 129),
    ('gift_offer_effect_id', 'not-a-uuid'), ('completed', 1),
])
def test_unknown_or_malformed_public_projection_is_rejected(key, value):
    from mira.domain.chapter_presentation import chapter_presentation
    with pytest.raises(ValueError):
        chapter_presentation(projection(**{key: value}))


def test_null_absence_and_inconsistent_role_binding():
    from mira.domain.chapter_presentation import chapter_presentation
    assert chapter_presentation(None) is None
    with pytest.raises(ValueError):
        chapter_presentation(projection(role_active=False))
    with pytest.raises(ValueError):
        chapter_presentation(projection(gift_offer_effect_digest=None))


def test_projection_schema_cannot_acquire_application_authority():
    from pydantic import ValidationError
    from mira.entrypoints.http.schemas import ChapterProjectionView
    with pytest.raises(ValidationError):
        ChapterProjectionView(**projection(session_token='synthetic-extra'))
    with pytest.raises(ValidationError):
        ChapterProjectionView(**projection(pending_transition='enable_private_memory'))


def test_explicit_button_input_binds_choice_and_exact_offer_without_audio_or_raw_proposal():
    from pydantic import ValidationError
    from mira.entrypoints.http.schemas import InputRequest
    choice = dict(choice='accept', offer_id='offer-one', offer_effect_id=str(uuid4()),
                  offer_effect_digest='a' * 64)
    data = dict(request_id=str(uuid4()), activity_seq=2, presentation_cutoff=3,
                text='我收下这张照片', chapter_choice=choice)
    assert InputRequest(**data).chapter_choice.choice == 'accept'
    for patch in (dict(text='我不接受'), dict(listening_utterance_id=str(uuid4())),
                  dict(chapter_choice={**choice, 'role_active': True}),
                  dict(chapter_choice={**choice, 'choice': 'grant_role'})):
        with pytest.raises(ValidationError):
            InputRequest(**{**data, **patch})


def test_http_projection_uses_wire_alias_and_is_never_accepted_as_authority():
    from fastapi.testclient import TestClient
    from mira.config.settings import Settings
    from mira.entrypoints.http.app import create_app
    app = create_app(Settings())
    with TestClient(app) as client:
        created = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
        path = '/api/v1/sessions/' + created['session']['session_id']
        headers = {'X-Mira-Session-Token': created['session_token']}
        assert created['session']['chapter_projection'] is None
        forged = client.post(path + '/inputs', headers=headers, json={
            'request_id': str(uuid4()), 'activity_seq': 1, 'presentation_cutoff': 0,
            'text': 'hello', 'chapter_projection': projection()})
        assert forged.status_code == 422
        unchanged = client.get(path, headers=headers).json()
        assert unchanged['revision'] == created['session']['revision']
        assert unchanged['chapter_projection'] is None

        # Inject only a synthetic server-owned view to exercise actual ASGI
        # response serialization. This is a DTO test, not a recognition receipt.
        from mira.domain.chapter_presentation import chapter_presentation
        actor = app.state.container.sessions.get(created['session']['session_id'], created['session_token'])
        actor._state = replace(actor._state, chapter_projection=chapter_presentation(projection()))
        returned = client.get(path, headers=headers).json()['chapter_projection']
        assert returned['schema'] == 'mira.xiahe-chapter.v1'
        assert 'schema_' not in returned
