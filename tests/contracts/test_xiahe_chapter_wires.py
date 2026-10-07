"""Active chapter plus ordinary long/short chat under inherited wire budgets."""
from dataclasses import replace
import json
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from mira.application.contracts import generation_context_data
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from tests.contracts.test_xiahe_chapter_actor import character,prepare,complete,advance_to_gift
from tests.contracts.test_character_control_bridge import Generation,candidate,ready_catalog
from tests.contracts.test_character_review_wire_limits import MeasuredWire
from tests.contracts.test_direct_provider_app import arguments
from tests.contracts.test_development_app_entry import wait_ready
from mira.domain.story import ReadinessCatalog


@pytest.mark.parametrize('turns',[5,10,20])
@pytest.mark.parametrize('chapter_phase',['recognized','gift_offered'])
def test_active_chapter_long_short_chat_keeps_one_version_and_original_budgets(turns,chapter_phase):
    c=character()
    if chapter_phase=='gift_offered':
        advance_to_gift(c)
    else:
        _,effects=prepare(c,'x.recognize',1,'我是夏禾',act='claim_role');complete(c,effects)
    # Synthetic prehistory is retained, while this test starts its HTTP Actor's
    # accepted-input counter at zero. No real stored session is being resumed.
    c.runtime.story=replace(c.runtime.story,epoch=0,input_fence_id=None,last_input_ids=())
    c.readiness=ReadinessCatalog('synthetic-active-chapter-wire',ready_catalog().records+c.readiness.records)
    milestone_history=c.runtime.story.chapter.milestones
    wire=MeasuredWire()
    controls=('outfit_cream_inner_only','accessory_star_clip','outfit_amber_raincoat','outfit_black_jacket')
    generation=Generation(lambda context:candidate(controls[(len(context.user_inputs)-1)//2%4],'emotion_normal')
        if len(context.user_inputs)%2 else candidate())
    app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,output_transport=wire,
        usage_profile='application',character_factory=lambda _:c,generation_request_limit=turns,
        session_turn_limit=turns,input_request_limit=turns*2,output_request_limit=turns*2))
    with TestClient(app) as client:
        created=client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())}).json()
        path='/api/v1/sessions/'+created['session']['session_id'];headers={'X-Mira-Session-Token':created['session_token']}
        sequence=0;accepted=[]
        for index in range(turns):
            text=(f'合成轮次{index}。'+('我喜欢仔细听一件日常小事，聊完再换话题。'*12 if index%2 else '我们先聊今天。'))
            accepted.append(text)
            response=client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),
                'activity_seq':index+1,'presentation_cutoff':sequence,'text':text})
            assert response.status_code==202,response.text
            state=wait_ready(client,path,headers)
            assert state['sealed'] and state['last_error'] is None
            if index%2==0:
                assert controls[index//2%4] in {row['value'] for row in state['active_grants']}
            for effect in state['active_grants']:
                sequence+=1
                receipt={key:effect[key] for key in ('digest','output_epoch','activity_seq')}
                receipt.update(effect_id=effect['id'],presentation_seq=sequence)
                assert client.post(path+'/receipts',headers=headers,json=receipt).status_code==200
            context=generation.contexts[-1]
            assert context.user_inputs==tuple(accepted)
            data=generation_context_data(context)
            assert tuple(data['user_inputs'])==tuple(accepted)
            chapter=data['character_story']['chapter']
            assert chapter['schema']=='mira.xiahe-chapter.v1'
            assert len(chapter['author_canon_for_current_beat'])<=1
            raw=json.dumps(data,ensure_ascii=False)
            assert raw.count(chapter['source_hash'])==1
            for row in chapter['author_canon_for_current_beat']:
                assert raw.count(row['text'])==1
        assert max(wire.input_sizes)<=32768
        assert max(wire.output_sizes)<=65536
        assert c.runtime.story.chapter.milestones==milestone_history
        assert c.runtime.story.chapter.stage.value==chapter_phase
        assert len(generation.contexts)==turns
        print('active-chapter-wire-bytes',chapter_phase,turns,
            {'input_max':max(wire.input_sizes),'output_max':max(wire.output_sizes),
             'generation_max':max(len(json.dumps(generation_context_data(ctx),ensure_ascii=False).encode()) for ctx in generation.contexts)})


def test_chapter_beat_cannot_evict_latest_environment_from_bounded_conversation():
    from mira.application.conversation_context import bound_conversation_data
    from mira.application.compiler import compile_range
    from mira.application.contracts import CandidateRange,EffectProposal,effect_data
    from mira.domain.models import EffectKind
    controls=compile_range(CandidateRange((EffectProposal(EffectKind.SCENE,'rain_window'),
        EffectProposal(EffectKind.SCENE,'xiahe_photo_handover')),'synthetic-control-history'),epoch=1,activity=1)
    rows=[effect_data(item) for item in controls]
    rows.extend(effect_data(compile_range(CandidateRange((EffectProposal(EffectKind.SUBTITLE,'普通聊天'+str(index)),),
        'synthetic-chat'),epoch=index+2,activity=index+2)[0]) for index in range(30))
    original={'user_text':'继续聊天','user_inputs':['继续聊天'],'presented_effects':rows,'audio_progress':[]}
    bounded=bound_conversation_data(original,max_bytes=4000)
    retained=bounded['conversation_history']['latest_control_receipts']
    assert retained['scene']['effect_id']==controls[0].id
    assert retained['chapter']['effect_id']==controls[1].id
    assert len(bounded['user_inputs'])==1 and bounded['user_inputs'][0]=='继续聊天'
    assert original['presented_effects']==rows
