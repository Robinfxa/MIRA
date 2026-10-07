"""Complete direct-HTTP/Actor/JEV-parser story loop with synthetic transports."""
import json
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mira.adapters.generation.direct_codex_responses import DirectCodexResponsesGenerationBackend,ResponsesRoute
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from mira.application.actor_story import SessionCharacterRuntime
from mira.application.story import StoryRuntime
from mira.domain.story import ReadinessCatalog,CapabilityRecord,CapabilityState,StoryNode,OfferStatus
from mira.adapters.review.jev import JevHttpResponse
from tests.contracts.test_actor_story_loop import definition
from tests.contracts.test_direct_provider_app import arguments
from tools.live_provider import ApiCredentialSource


class SemanticWire:
    def __init__(self):self.calls=[]
    async def __call__(self,raw,**_):
        request=json.loads(raw);self.calls.append(request)
        text=request['state']['context']['user_text'];answers={}
        for key,question in request['questions'].items():
            suffix=key.rsplit(':',1)[-1]
            if question['type']=='noul':
                value={'story_relevance':1,'story_willingness':1 if text=='yes' else .5,
                       'story_refusal':1 if text=='no' else 0}.get(suffix,0)
                answers[key]={'type':'noul','noul':value}
            elif 'contract' not in request['state']:
                answers[key]={'type':'choice','choice':'none','confidence':1,
                    'probabilities':{name:int(name=='none') for name in question['criteria']}}
            else:
                chosen='unknown' if suffix=='affect_supported' else 'allow'
                answers[key]={'type':'choice','choice':chosen,'confidence':.9,
                    'probabilities':{name:.95 if name==chosen else .025 for name in ('allow','reject','unknown')}}
        return JevHttpResponse(200,json.dumps({'model':'jev-1.13.0','answers':answers,
            'usage':{'input_tokens':10,'output_tokens':2}}).encode())


@pytest.mark.parametrize('choice',['yes','no'])
@pytest.mark.parametrize('built_in',[False,True])
def test_direct_responses_and_actual_jev_parser_drive_receipt_bound_rain_story(choice,built_in):
    models=[];characters=[];review=SemanticWire()
    async def handle(request):
        body=json.loads(request.content);prompt=json.loads(body['input'][0]['content'][0]['text'])
        models.append(prompt);text=prompt['facts']['user_text'];contract=prompt['character_proposal_contract']
        if text=='offer':
            subtitle='一起看看窗外的雨吗？';meta={'transition_id':'t.offer','signal':'offer_rain',
                'offer_id':contract['next_offer_id'],'draft_cue':subtitle}
        elif text=='yes':
            subtitle='我会换上雨衣。';meta={'transition_id':'t.yes','signal':'accept_raincoat',
                'offer_id':contract['active_offer_id'],'target_capabilities':['mira.outfit.amber_raincoat']}
        else:subtitle='那我们留在室内聊。';meta={'transition_id':'t.chat','signal':'chat'}
        candidate=json.dumps({'effects':[{'kind':'subtitle','value':subtitle}],'story_proposal':meta},ensure_ascii=False)
        item={'type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':candidate,'annotations':[]}]}
        def event(kind,**value):return ('event: '+kind+'\ndata: '+json.dumps({'type':kind,**value},ensure_ascii=False)+'\n\n').encode()
        wire=event('response.output_item.done',output_index=0,item=item)+event('response.completed',response={'status':'completed','output':None})
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):yield wire
            async def aclose(self):pass
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
    backend=DirectCodexResponsesGenerationBackend(ResponsesRoute.OPENAI_API,'synthetic-model',
        ApiCredentialSource(SecretStr('synthetic-token')),admitted=True,request_limit=2,
        transport=httpx.MockTransport(handle),speech_enabled=False)
    def character_factory(state):
        from mira.bootstrap.character_story import builtin_definition
        runtime=SessionCharacterRuntime(StoryRuntime(builtin_definition() if built_in else definition(),state.session_id),ReadinessCatalog('synthetic-ready',(
            CapabilityRecord('mira.outfit.amber_raincoat',CapabilityState.READY,'test-assets',
                ('outer.amber','inner.cream'),'synthetic-proof'),)))
        characters.append(runtime);return runtime
    app=create_direct_provider_app(**arguments(generation=backend,route='openai_api',api_billing_authorized=True,
        input_transport=review,output_transport=review,generation_request_limit=2,session_turn_limit=2,
        input_request_limit=4,output_request_limit=4,character_factory=character_factory))
    with TestClient(app) as client:
        created=client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())}).json()
        path='/api/v1/sessions/'+created['session']['session_id'];headers={'X-Mira-Session-Token':created['session_token']}
        def submit(text,activity,cutoff):
            assert client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),'activity_seq':activity,
                'presentation_cutoff':cutoff,'text':text}).status_code==202
            until=time.monotonic()+3
            while time.monotonic()<until:
                state=client.get(path,headers=headers).json()
                if state['sealed'] or state['last_error']:return state
                time.sleep(.005)
            pytest.fail('synthetic story turn did not terminate')
        first=submit('offer',1,0)
        assert first['sealed'],(first.get('last_error'),len(review.calls),[len(json.dumps(x).encode()) for x in review.calls])
        effect=first['active_grants'][0]
        receipt={key:effect[key] for key in ('digest','output_epoch','activity_seq')}
        receipt.update(effect_id=effect['id'],presentation_seq=1)
        response=client.post(path+'/receipts',headers=headers,json=receipt)
        assert response.status_code==200,response.text
        assert characters[0].runtime.story.node is StoryNode.AWAIT_RAIN_CHOICE
        second=submit(choice,2,1)
        assert second['sealed'],second.get('last_error')
        sequence=1
        for effect in second['active_grants']:
            sequence+=1
            receipt={key:effect[key] for key in ('digest','output_epoch','activity_seq')}
            receipt.update(effect_id=effect['id'],presentation_seq=sequence)
            assert client.post(path+'/receipts',headers=headers,json=receipt).status_code==200
        state=characters[0].runtime.story
        assert state.node is (StoryNode.RAIN_VIEW if choice=='yes' else StoryNode.CAFE_CHAT)
        assert len(state.episodes)==(1 if choice=='yes' else 0)
        if choice=='no':assert state.offer_status is OfferStatus.DECLINED
        assert state.relationship_delta==0
        assert len(models)==2 and len(review.calls)==4
        outputs=[call for call in review.calls if 'contract' in call['state']]
        for model,stage in zip(models,outputs):
            from tests.contracts.test_character_control_bridge import expand_v4_state
            assert expand_v4_state(stage['state'])['context']['character_story']==model['facts']['character_story']
