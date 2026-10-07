"""Subscription request counts are optional; synthetic transport, never live service IO."""
import asyncio
import json
from dataclasses import replace

import pytest

from mira.adapters.generation.direct_codex_responses import DirectResponsesError, ResponsesRoute
from mira.application.contracts import CandidateRange
from mira.application.diagnostic_errors import classify_failure, public_error_code
from mira.application.session_actor import RuntimeLimits
from mira.bootstrap.development_usage import UsageProfile
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.config.loader import ConfigurationError
from mira.config.settings import Settings
from tests.contracts.test_direct_codex_responses import backend, response, CONTEXT, collect
from tests.contracts.test_direct_luna_tools import wire, message, tool, definitions, result
from tests.contracts.test_native_character_tools import native
from tests.contracts.test_authored_photo_events import receipt
from tests.contracts.test_development_review_composition import finish
from tests.contracts.test_luna_tool_actor import wait_state
from tests.contracts.test_conversation_first import voice_options
from tools import live_provider as cli


def parsed(route='chatgpt_subscription', *extra):
    return cli._parser().parse_args(['check','--provider',route,'--model','gpt-6-luna',
        '--env-file','/tmp/unused-synthetic-env',*extra])


def test_route_defaults_and_explicit_finite_values_are_separate():
    subscription=parsed(); api=parsed('openai_api')
    assert cli._generation_request_limit(subscription) is None
    assert cli._session_turn_limit(subscription) is None
    assert cli._generation_request_limit(api)==20 and cli._session_turn_limit(api)==20
    finite=parsed('chatgpt_subscription','--generation-requests','7','--turns','9')
    assert cli._generation_request_limit(finite)==7 and cli._session_turn_limit(finite)==9
    assert not subscription.local_unlimited
    assert (subscription.stt_requests,subscription.tts_requests,subscription.stt_max_seconds,subscription.tts_max_seconds)==(None,20,120,30)
    assert subscription.story_image_max_attempts==1


@pytest.mark.asyncio
async def test_three_hundred_real_actor_turns_and_one_hundred_tools_stay_bounded():
    turn_number=0
    async def handle(request):
        body=json.loads(request.content)
        continuation=any(item.get('type')=='function_call_output' for item in body['input'])
        if turn_number%3==0 and not continuation:return response(wire([tool()]))
        return response(wire([message('合成的完整回复。')]))
    generation,source,requests=backend(handle,request_limit=None)
    actor=native(None,tools=generation,wait=1)
    actor._limits=RuntimeLimits(3,None,128)
    sequence=0
    try:
        for turn_number in range(1,301):
            await actor.submit(request_id=f'long-{turn_number}',activity_seq=turn_number,
                cutoff=sequence,text=f'合成输入{turn_number}')
            if turn_number==3:
                state=await wait_state(actor,lambda s:any(e.kind.value=='media' for e in s.active_grants))
                effect=next(e for e in state.active_grants if e.kind.value=='media')
                sequence+=1;await actor.receipt(receipt(effect,sequence))
            state=await finish(actor)
            assert state.last_error is None, (turn_number,state.last_error)
            for effect in state.active_grants:
                if not any(saved.effect_id==effect.id for saved in state.receipts):
                    sequence+=1;await actor.receipt(receipt(effect,sequence))
        state=await actor.snapshot()
        assert len(requests)==source.calls==400
        assert generation._remaining is None and generation._reserved==0
        assert len(state.user_inputs)<=65 and len(state.issued_effects)<=128
        assert len(actor._request_fingerprints)<=64 and len(actor._decision_inputs)<=64
        assert state.retired_user_inputs>=235
        assert actor._accepted_turn_count==300
    finally:await actor.close()


@pytest.mark.asyncio
async def test_explicit_finite_exhaustion_has_own_safe_code_and_no_extra_request():
    async def handle(_):return response(wire([message()]))
    generation,source,requests=backend(handle,request_limit=1)
    await generation.open_tool_turn(CONTEXT,definitions()).start()
    with pytest.raises(DirectResponsesError) as caught:
        await generation.open_tool_turn(CONTEXT,definitions()).start()
    error=caught.value
    assert error.code=='generation_budget_exhausted' and error.stage=='admission'
    assert public_error_code(error.code)=='generation_budget_exhausted'
    assert classify_failure(error).code.value=='limit_reached'
    assert error.generation_diagnostic.http_status is None
    assert len(requests)==source.calls==1


@pytest.mark.asyncio
async def test_final_reserved_continuation_and_provider_429_remain_distinct():
    for limited in (False,True):
        async def handle(_):
            if len(requests)==1:return response(wire([tool()]))
            if limited:return response(b'{"error":{"code":"insufficient_quota"}}',status=429)
            return response(wire([message()]))
        generation,source,requests=backend(handle,request_limit=2)
        turn=generation.open_tool_turn(CONTEXT,definitions());await turn.start()
        with pytest.raises(DirectResponsesError) as caught:await collect(generation)
        assert caught.value.code=='generation_budget_exhausted'
        assert generation._remaining==generation._reserved==1
        if limited:
            with pytest.raises(DirectResponsesError) as caught:await turn.continue_after_tool(result(),CONTEXT)
            assert caught.value.code=='quota_exhausted' and caught.value.http_status==429
        else:assert type(await turn.continue_after_tool(result(),CONTEXT)) is CandidateRange
        assert generation._remaining==generation._reserved==0 and len(requests)==source.calls==2


def test_official_api_and_probe_cannot_take_unlimited_generation():
    async def handle(_):raise AssertionError('no requests')
    with pytest.raises(ValueError):backend(handle,request_limit=None,route=ResponsesRoute.OPENAI_API)
    generation,_,_=backend(handle,request_limit=None)
    with pytest.raises(ConfigurationError):
        create_direct_provider_app(generation=generation,tool_generation=generation,model='gpt-6-luna',
            settings=Settings(),route='chatgpt_subscription',authorized=True,
            generation_request_limit=None,session_turn_limit=None)


@pytest.mark.parametrize('local_options',[{}, {'local_listening_unlimited':False}])
def test_unlimited_voice_defaults_preserve_explicit_service_caps_and_legacy_opt_in(local_options):
    from fastapi.testclient import TestClient
    from tests.contracts.test_conversation_first import session
    async def handle(_):raise AssertionError('no requests')
    generation,_,_=backend(handle,request_limit=None)
    voice=voice_options()
    voice['voice_usage_limits']=replace(voice['voice_usage_limits'],usage_profile=UsageProfile.APPLICATION)
    app=create_direct_provider_app(generation=generation,tool_generation=generation,model='gpt-6-luna',
        settings=Settings(),route='chatgpt_subscription',authorized=True,usage_profile=UsageProfile.APPLICATION,
        generation_request_limit=None,session_turn_limit=None,**local_options,**voice)
    assert app.state.usage_declaration.codex_requests is None
    assert app.state.usage_declaration.tts_requests==app.state.usage_declaration.stt_requests==1
    with TestClient(app) as client:
        path,headers=session(client)
        capabilities=client.get(path+'/voice-capabilities',headers=headers).json()
        container=app.state.container
        limits=container.listening_leases.limits
        if local_options.get("local_listening_unlimited") is False:
            assert limits.max_seconds==10 and limits.max_utterances==12
            assert limits.max_streams_per_session==4 and limits.max_total_streams==1
        else:
            assert limits.max_seconds is limits.max_utterances is None
            assert limits.max_streams_per_session is limits.max_total_streams is None


def test_check_renders_null_limits_without_auth_or_generation(tmp_path, monkeypatch, capsys):
    env=tmp_path/'synthetic.env';env.write_text('');env.chmod(0o600)
    monkeypatch.setattr(cli,'_generation',lambda *_:pytest.fail('no model or auth lookup'))
    assert cli.main(['check','--provider','chatgpt_subscription','--model','gpt-6-luna',
        '--env-file',str(env)])==0
    value=json.loads(capsys.readouterr().out)
    assert value['generation_request_limit'] is None and value['turn_limit'] is None
    assert value['generation_count_policy']==value['text_turn_policy']=='unlimited'
    assert value['local_interaction_policy']=='unlimited'
    assert value['story_images']['readiness']['state']=='disabled'


def test_story_image_readiness_accepts_unlimited_dialogue_without_expanding_image_budget(monkeypatch):
    import mira.bootstrap.story_image_provider as images
    from types import SimpleNamespace
    options=SimpleNamespace(enabled=True,authorize_data_to_openai=True,
        authorize_subscription_usage=True,authorize_custom_brief=True,authorize_api_spend=False)
    monkeypatch.setattr(cli,'_story_image_inputs',lambda *_:(options,None))
    monkeypatch.setattr(images,'describe_story_images',lambda **_:{'max_attempts':1})
    monkeypatch.setattr(images,'describe_story_image_readiness',lambda **_:{'state':'enabled','generation_tool':'present'})
    args=parsed();args.story=True
    value=cli._story_image_declaration(args,Settings())
    assert value['readiness']['state']=='enabled' and value['max_attempts']==1


@pytest.mark.asyncio
async def test_actor_preserves_presented_history_on_finite_budget_exhaustion():
    async def handle(_):return response(wire([message('已呈现的合成回复。')]))
    generation,source,requests=backend(handle,request_limit=1)
    actor=native(None,tools=generation)
    try:
        await actor.submit(request_id='first',activity_seq=1,cutoff=0,text='第一句')
        state=await finish(actor);shown=state.active_grants[0]
        await actor.receipt(receipt(shown,1))
        await actor.submit(request_id='second',activity_seq=2,cutoff=1,text='第二句已接受')
        state=await finish(actor)
        assert state.last_error=='generation_budget_exhausted' and state.phase.value=='error'
        assert shown in state.presented_effects and state.user_inputs[-1]=='第二句已接受'
        await actor.submit(request_id='third',activity_seq=3,cutoff=1,text='第三句再次尝试')
        state=await finish(actor)
        assert state.last_error=='generation_budget_exhausted' and len(requests)==source.calls==1
    finally:await actor.close()


@pytest.mark.asyncio
async def test_unlimited_cancel_releases_reservation_without_retry_or_stale_continuation():
    from tests.contracts.test_direct_codex_responses import BlockingStream
    from tests.contracts.test_direct_luna_tools import done
    stream=BlockingStream(done(tool()))
    async def handle(_):return response(b'',stream=stream)
    generation,source,requests=backend(handle,request_limit=None)
    turn=generation.open_tool_turn(CONTEXT,definitions())
    task=asyncio.create_task(turn.start());await stream.entered.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert stream.closed and generation._reserved==0 and generation._remaining is None
    with pytest.raises(DirectResponsesError):await turn.continue_after_tool(result(),CONTEXT)
    assert len(requests)==source.calls==1
