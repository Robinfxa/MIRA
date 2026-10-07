"""Current product entry selects v2; explicit historical v1 remains supported."""
import json
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from mira.bootstrap import development_app
from mira.config.settings import Settings
from mira.application.decision_policy import USER_DEVELOPMENT_0_6_V2
from tests.contracts.test_development_app_entry import public_runtime, wait_ready
from tests.contracts.test_codex_generation import SyntheticTransport, event, agent, terminal
from tests.contracts.test_development_review_composition import SyntheticJevTransport
from mira.adapters.review.jev import JevHttpResponse

MODEL='jev-1.13.0'

def product_choice(label, probability):
    other=(1-probability)/2
    return {'type':'choice','choice':label,
        'confidence':(probability-1/3)/(1-1/3),
        'probabilities':{name:probability if name==label else other
                         for name in ('allow','reject','unknown')}}

class ProductOutputTransport:
    def __init__(self, choice, probability):
        self.choice,self.probability=choice,probability
        self.calls=[]
    async def __call__(self,payload,**_kwargs):
        request=json.loads(payload);self.calls.append(request)
        answers={}
        for key,question in request['questions'].items():
            if question['type']=='noul':answers[key]={'type':'noul','noul':0.5}
            elif key.endswith(':o3'):answers[key]=product_choice(self.choice,self.probability)
            else:answers[key]=product_choice('allow',0.9)
        return JevHttpResponse(200,json.dumps({'model':MODEL,'answers':answers,
            'usage':{'input_tokens':12,'output_tokens':7}}).encode())

@pytest.mark.parametrize(('choice','probability','expected'),[
    ('reject',.52,'review_uncertain'),('reject',.9,'review_not_allowed'),('allow',.9,None)])
def test_default_product_policy_handles_weak_reject_as_uncertainty(choice,probability,expected):
    generated={'effects':[{'kind':'subtitle','value':'你好。'},{'kind':'pose','value':'face_warm'}]}
    codex=SyntheticTransport(events=[event('item/completed',item=agent(json.dumps(generated))),terminal()])
    async def native(*_):return codex
    review=ProductOutputTransport(choice,probability)
    app=development_app.create_development_app(runtime=public_runtime(),settings=Settings(),route_kind='public',
        input_transport=SyntheticJevTransport(),output_transport=review,authorized=True,codex_transport_factory=native)
    with TestClient(app) as client:
        created=client.post('/api/v1/sessions',json={'client_instance_id':str(uuid4())}).json()
        path='/api/v1/sessions/'+created['session']['session_id'];headers={'X-Mira-Session-Token':created['session_token']}
        assert client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),'activity_seq':1,
            'presentation_cutoff':0,'text':'请写一句你好。'}).status_code==202
        state=wait_ready(client,path,headers)
    assert state['last_error']==expected
    assert bool(state['active_grants']) is (expected is None)
    assert codex.closed
    assert review.calls
    assert all(call['state']['contract']['policy_revision']=='mira-output-interaction-v1' for call in review.calls)

def test_text_cli_explicitly_selects_current_v2(monkeypatch):
    import tools.live_dev as cli
    from mira.bootstrap.development_usage import UsageProfile
    admission=SimpleNamespace(runtime=public_runtime(),route_kind='public',authorized=True,
        usage_profile=UsageProfile.PROBE,
        limits=SimpleNamespace(codex_requests=1,session_turns=1,input_jev_requests=2,output_jev_requests=2,
                               input_jev_timeout_seconds=10,output_jev_timeout_seconds=10))
    monkeypatch.setattr(cli,'_read_admission',lambda _:admission)
    monkeypatch.setattr(cli,'_load_settings',lambda *_,**__:Settings())
    monkeypatch.setattr(cli,'_check_settings',lambda *_,**__:None)
    monkeypatch.setattr(cli,'_prepare_frontend',lambda:None)
    monkeypatch.setattr(development_app,'jev_transport_from_settings',lambda _:object())
    seen=[]
    class Captured(Exception):pass
    def capture(**kw):seen.append(kw['decision_policy']);raise Captured()
    monkeypatch.setattr(development_app,'create_development_app',capture)
    with pytest.raises(Captured):cli.main(['serve','--env-file','/synthetic/mira.env','--admission','/synthetic/admission.json'])
    assert seen==[USER_DEVELOPMENT_0_6_V2]
