"""Synthetic production hooks and real HTTPX/Actor envelopes, never model quality."""
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from mira.application.contracts import GenerationContext, generation_context_data
from mira.application.story import StoryRuntime
from mira.bootstrap.character_story import builtin_definition


def context(inputs, effects=()):
    return GenerationContext(inputs[-1], tuple(inputs), effects, len(inputs),
        character_story=StoryRuntime(builtin_definition(), 'synthetic-topic').project().projection)


def topics(value):
    return generation_context_data(value)['first_person_dialogue'].get('optional_topics', {})


@pytest.mark.parametrize('inputs,expected', [
    (('夏禾是谁？',), {'xiahe'}),
    (('夏禾是谁？', '她和那张照片有什么关系？'), {'xiahe'}),
    (('说说夏禾', '先不聊她，17乘19是多少？'), set()),
    (('说说夏禾', '先不聊她，17乘19是多少？', '回到刚才那张纸质照片，为什么拖那么久？'), {'print_selection'}),
    (('说说夏禾', '象棋怎么走？', '然后呢？'), set()),
    (('刚才那个呢？',), set()),
    (('别再聊夏禾了，我们说点别的',), set()),
    (('不想听这段，也不想看雨',), set()),
    (('我想聊聊象棋，不聊照片了',), set()),
    (('先安静一下',), set()),
    (('有不同的照片吗？',), set()),
    (('我喜欢冷色调，你呢？',), {'photo_light'}),
    (('第一次自己去海边，有什么记得清楚的？',), {'first_trip'}),
    (('旅行时有过什么小糗事吗？', '后来怎么解决的？'), {'small_stories'}),
    (('这个星星发卡有什么故事？',), {'small_objects'}),
    (('雨小一点以后你想看看什么？',), {'after_rain'}),
])
def test_installed_shared_hook_ranks_optional_resources_without_topic_authority(inputs, expected):
    value = context(inputs)
    before = value.character_story
    view = topics(value)
    selected = {row['id'] for row in view.get('topics', [])}
    assert expected <= selected if expected else not selected
    assert len(selected) <= 2
    assert value.character_story is before
    if expected:
        assert view['binding_reference'] == 'character_story.projection_id'
        assert 'optional' in view['rule'] and 'No actions' in view['rule']
        assert len(json.dumps(view, ensure_ascii=False).encode()) <= 1400
        assert not {'current_topic', 'intent', 'effect_proposal'} & view.keys()
        known = {entry.entry_id for entry in before.known_canon}
        assert all(set(row['canon_source_ids']) <= known for row in view['topics'])
    else:
        assert 'optional_topics' not in generation_context_data(value)['first_person_dialogue']


def test_current_input_wins_over_old_topics_and_pending_output():
    from mira.domain.models import Effect, EffectKind
    old = Effect('old', EffectKind.SUBTITLE, '夏禾还在等那张纸质照片。', 'a'*64, 1, 1)
    value = replace(context(('说说夏禾', '讨论象棋吧'), (old,)), accepted_prefix=(old,))
    assert not topics(value)


@pytest.mark.parametrize('text', [
    '怎么计算17乘19？', '为什么天空是蓝色？', '第一次学象棋，先学什么？',
    '然后帮我分析这段代码',
])
def test_new_subject_does_not_inherit_topic_from_generic_question_words(text):
    assert not topics(context(('说说夏禾', text)))


def test_stop_and_noncontiguous_activity_never_invent_reply_turn_association():
    from mira.domain.models import Effect, EffectKind
    # Activity sequence includes Stop and other activity, not just accepted input.
    # The DTO has no previous-input epoch map: no reply-to-turn guess is permitted.
    reply = Effect('before-stop', EffectKind.SUBTITLE, '夏禾还在等纸质照片。', 'a'*64, 5, 19)
    value = replace(context(('你好', '然后呢？'), (reply,)), output_epoch=8)
    data = generation_context_data(value)
    assert not topics(value)
    assert data['presented_effects'][0]['activity_seq'] == 19
    # A prior accepted subject remains available independently of activity gaps.
    assert topics(replace(value, user_inputs=('聊聊夏禾', '然后呢？')))['topics'][0]['id'] == 'xiahe'
    # An accidentally matching count is not a valid receipt correlation either.
    misleading = replace(reply, activity_seq=1)
    assert not topics(replace(value, presented_effects=(misleading,)))


def test_repeated_canon_metadata_compacts_losslessly_without_changing_a_mismatch():
    from copy import deepcopy
    from mira.adapters.review.jev import _compact_v4_snapshot
    from tests.contracts.test_character_control_bridge import expand_v4_state
    common = {'approval_basis':'explicit_composition_selection', 'author_created':True,
              'disclosure_level':'public', 'source':'authored_backstory'}
    rows = [{**common, 'id':'one', 'source_revision':2, 'text':'First fact'},
            {**common, 'id':'two', 'source_revision':3, 'text':'Second fact'},
            {**common, 'id':'different', 'source':'different', 'text':'Keep distinct'}]
    state = {'context': {'character_story': {'approved_canon':rows}, 'presented_effects':[]},
             'contract': {'character_facts':[], 'allowed_controls':[]}}
    original = deepcopy(state)
    _compact_v4_snapshot(state)
    assert state['canon_provenance'] == common
    assert rows[0]['provenance_reference'] == 'state.canon_provenance'
    assert rows[1]['source_revision'] == 3
    assert rows[2]['source'] == 'different' and 'provenance_reference' not in rows[2]
    assert expand_v4_state(state) == original
    assert len(json.dumps(state)) < len(json.dumps(original))


def test_optional_guidance_yields_budget_before_any_reliable_fact():
    from mira.adapters.generation.codex_support.payload import build_prompt
    from mira.adapters.generation.codex_support.types import CodexLimits
    value = context(('夏禾是谁？',))
    full = generation_context_data(value, max_context_bytes=None)
    omitted = full['first_person_dialogue'].pop('optional_topics')
    full['first_person_dialogue']['optional_topics_omitted'] = len(omitted['topics'])
    size = len(json.dumps(full, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
    assert generation_context_data(value, max_context_bytes=size) == full
    prompt = json.loads(build_prompt(value, CodexLimits()))
    omitted = prompt['facts']['first_person_dialogue'].pop('optional_topics')
    prompt['facts']['first_person_dialogue']['optional_topics_omitted'] = len(omitted['topics'])
    limit = len(json.dumps(prompt, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
    assert json.loads(build_prompt(value, CodexLimits(max_prompt_bytes=limit))) == prompt


@pytest.mark.asyncio
async def test_direct_media_continuation_keeps_shared_context_and_media_contract():
    from tests.contracts.test_direct_codex_responses import backend, response
    from tests.contracts.test_direct_luna_tools import definitions, tool, wire, message, result
    value = context(('聊聊第一次海边，然后展示内置照片。',))
    sent = []
    async def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        return response(wire([tool()] if len(sent) == 1 else [message()]))
    instance, _, _ = backend(handler, request_limit=2)
    turn = instance.open_tool_turn(value, definitions())
    await turn.start()
    fresh = replace(value, photo_visibility_revision=3)
    await turn.continue_after_tool(result(), fresh)
    first = json.loads(sent[0]['input'][0]['content'][0]['text'])
    continuation = json.loads(sent[1]['input'][-1]['content'][0]['text'])
    assert first['facts']['first_person_dialogue']['optional_topics'] == topics(value)
    assert continuation['facts']['first_person_dialogue'] == generation_context_data(fresh)['first_person_dialogue']
    assert first['media_dialogue_contract'] == continuation['media_dialogue_contract']
    assert continuation['tool_turn_state']['photo_visibility_revision'] == 3
    assert sent[1]['input'][-2]['type'] == 'function_call_output'


@pytest.mark.parametrize('turns', [5, 10, 20])
def test_actual_actor_direct_request_and_jev_share_topics_and_self_at_five_ten_twenty_turns(turns):
    from mira.adapters.generation.direct_codex_responses import DirectCodexResponsesGenerationBackend, ResponsesRoute
    from mira.application.actor_story import SessionCharacterRuntime
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
    from tests.contracts.test_direct_codex_responses import CredentialSource, item_done, completed, response
    from tests.contracts.test_character_control_bridge import ready_catalog
    from tests.contracts.test_character_control_bridge import expand_v4_state
    from tests.contracts.test_character_review_wire_limits import MeasuredWire
    from tests.contracts.test_direct_provider_app import arguments
    from tests.contracts.test_development_app_entry import wait_ready

    generated, reviewed = [], []
    class Wire(MeasuredWire):
        async def __call__(self, raw, **kwargs):
            data = json.loads(raw)
            if 'contract' in data['state']:
                reviewed.append(expand_v4_state(data['state'])['context'])
            return await super().__call__(raw, **kwargs)
    async def handler(request):
        body = json.loads(request.content)
        facts = json.loads(body['input'][0]['content'][0]['text'])['facts']
        generated.append(facts)
        effects = [{'kind': 'subtitle', 'value': '这是合成来源与传输验证。'}]
        if len(generated) % 2:
            effects.append({'kind': 'pose', 'value': 'emotion_normal'})
        return response(item_done(json.dumps({'effects': effects}, ensure_ascii=False)) + completed())
    backend = DirectCodexResponsesGenerationBackend(ResponsesRoute.CHATGPT_SUBSCRIPTION,
        'gpt-6-luna', CredentialSource(), admitted=True, request_limit=turns,
        transport=httpx.MockTransport(handler), speech_enabled=False)
    runtime = StoryRuntime(builtin_definition(), 'synthetic-production-topic')
    wire = Wire()
    app = create_direct_provider_app(**arguments(generation=backend, input_transport=wire,
        output_transport=wire, usage_profile='application',
        character_factory=lambda _: SessionCharacterRuntime(runtime, ready_catalog()),
        generation_request_limit=turns, session_turn_limit=turns,
        input_request_limit=turns*2, output_request_limit=turns*2))
    texts = ('夏禾是谁？', '她和那张照片有什么关系？', '先不聊她，17乘19是多少？',
             '象棋怎么走？', '回到纸质照片，为什么拖那么久？')
    with TestClient(app) as client:
        created = client.post('/api/v1/sessions', json={'client_instance_id': str(uuid4())}).json()
        path = '/api/v1/sessions/' + created['session']['session_id']
        headers = {'X-Mira-Session-Token': created['session_token']}
        seq = 0
        for index in range(turns):
            assert client.post(path+'/inputs', headers=headers, json={'request_id':str(uuid4()),
                'activity_seq':index+1, 'presentation_cutoff':seq, 'text':texts[index % len(texts)]}).status_code == 202
            state = wait_ready(client, path, headers)
            assert state['sealed'] and state['last_error'] is None
            assert len(state['active_grants']) == (2 if index % 2 == 0 else 1)
            for effect in state['active_grants']:
                seq += 1
                receipt = {key:effect[key] for key in ('digest','output_epoch','activity_seq')}
                receipt.update(effect_id=effect['id'],presentation_seq=seq)
                assert client.post(path+'/receipts',headers=headers,json=receipt).status_code == 200
        assert len(generated) == turns
        assert len(reviewed) == (turns+1)//2
        for actual, direct in zip(reviewed, generated[::2]):
            assert actual['user_text'] == direct['user_text']
            left, right = actual['first_person_dialogue'], direct['first_person_dialogue']
            assert left['self_continuity'] == right['self_continuity']
            if left.get('optional_topics_omitted'):
                assert 'optional_topics' not in left
                assert left['optional_topics_omitted'] == len(right['optional_topics']['topics'])
            else:
                assert left.get('optional_topics') == right.get('optional_topics')
            assert actual['character_story'] == direct['character_story']
        assert max(wire.input_sizes) <= 32768 and max(wire.output_sizes) <= 65536
        assert any(topics(context((text,))) for text in texts)
        assert not runtime.story.relationship_delta
        print('joined-production-envelope',turns,{'input_max':max(wire.input_sizes),'output_max':max(wire.output_sizes)})


def test_relevant_topics_and_controls_keep_original_probe_budget():
    from mira.application.actor_story import SessionCharacterRuntime
    from mira.bootstrap.direct_provider_app import create_direct_provider_app
    from tests.contracts.test_character_control_bridge import Generation, candidate, ready_catalog, expand_v4_state
    from tests.contracts.test_character_review_wire_limits import MeasuredWire
    from tests.contracts.test_direct_provider_app import arguments
    from tests.contracts.test_development_app_entry import wait_ready
    wire = MeasuredWire()
    runtime = StoryRuntime(builtin_definition(), "synthetic-topic-control-budget")
    character = SessionCharacterRuntime(runtime, ready_catalog())
    controls = ("outfit_cream_inner_only", "accessory_star_clip", "outfit_amber_raincoat", "outfit_black_jacket")
    generation = Generation(lambda context: candidate(controls[len(context.user_inputs) - 1], "emotion_normal"))
    app = create_direct_provider_app(**arguments(generation=generation,
        input_transport=wire, output_transport=wire, character_factory=lambda _: character,
        generation_request_limit=4, session_turn_limit=4, input_request_limit=8, output_request_limit=8))
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions", json={"client_instance_id": str(uuid4())}).json()
        path = "/api/v1/sessions/" + created["session"]["session_id"]
        headers = {"X-Mira-Session-Token": created["session_token"]}
        sequence = 0
        for index, control in enumerate(controls):
            text = "聊聊夏禾和纸质照片。Please use " + control + "."
            assert client.post(path + "/inputs", headers=headers, json={"request_id": str(uuid4()),
                "activity_seq": index + 1, "presentation_cutoff": sequence, "text": text}).status_code == 202
            state = wait_ready(client, path, headers)
            assert state["sealed"] and state["last_error"] is None
            assert {row["value"] for row in state["active_grants"]} >= {control, "emotion_normal"}, (
                index, wire.input_sizes, wire.output_sizes, state["active_grants"])
            for effect in state["active_grants"]:
                sequence += 1
                receipt = {key: effect[key] for key in ("digest", "output_epoch", "activity_seq")}
                receipt.update(effect_id=effect["id"], presentation_seq=sequence)
                assert client.post(path + "/receipts", headers=headers, json=receipt).status_code == 200
        outputs = [expand_v4_state(call['state']) for call in wire.calls if 'contract' in call['state']]
        assert len(outputs) == 4
        for index, output in enumerate(outputs):
            dialogue = output['context']['first_person_dialogue']
            assert dialogue['optional_topics_omitted'] == 2
            assert 'optional_topics' not in dialogue
            reliable = output['contract']['snapshot']['reliable_inputs']
            assert len(reliable) == index + 1
            assert all('夏禾' in row['text'] for row in reliable)
        assert len(wire.input_sizes) == len(wire.output_sizes) == 4
        assert max(wire.input_sizes) <= 16384
        assert max(wire.output_sizes) <= 32768
        print("independent-relevant-topic-probe", {"input": wire.input_sizes, "output": wire.output_sizes})


@pytest.mark.asyncio
async def test_stop_and_nonconsecutive_activity_never_bind_older_reply_to_previous_input():
    from mira.application.contracts import CandidateRange, EffectProposal, generation_context_data
    from mira.domain.models import EffectKind
    from tests.contracts.test_actor_story_loop import acknowledge, turn
    from tests.contracts.test_character_control_bridge import setup
    replies = ("夏禾提到过那张纸质照片。", "323。", "合成的澄清回复。")
    def output(context):
        return CandidateRange((EffectProposal(EffectKind.SUBTITLE, replies[len(context.user_inputs) - 1]),), "synthetic")
    actor, character, generation, _ = setup(output)
    try:
        first = await turn(actor, "随便说说吧。", 2)
        assert first.sealed and first.last_error is None
        await acknowledge(actor, first.active_grants[0], 1)
        await actor.stop(activity_seq=3, cutoff=1)
        second = await turn(actor, "17乘19是多少？", 4, 1)
        assert second.sealed and second.last_error is None
        # The arithmetic reply is stopped before any presentation receipt.
        await actor.stop(activity_seq=5, cutoff=1)
        third = await turn(actor, "后来呢？", 6, 1)
        assert third.sealed and third.last_error is None
        facts = generation_context_data(generation.contexts[-1])
        assert facts["user_inputs"] == ("随便说说吧。", "17乘19是多少？", "后来呢？")
        assert len(facts["presented_effects"]) == 1
        assert facts["presented_effects"][0]["activity_seq"] == 2
        assert "optional_topics" not in facts["first_person_dialogue"], (
            "An older activity_seq happened to equal len(user_inputs)-1; it is not the previous turn")
        assert character.runtime.story.episodes == ()
        assert character.runtime.story.relationship_delta == 0
    finally:
        await actor.close()
