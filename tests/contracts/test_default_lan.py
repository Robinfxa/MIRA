"""Default CLI and real HTTP admission with injected providers; no LAN probing."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from tools import live_provider as cli
from tools import private_device_access as access
from tests.contracts.test_luna_native_bootstrap import NativeGeneration, env, args

LAN = 'http://192.168.2.13:8000'
LOCAL = 'http://127.0.0.1:8000'
COOKIE = 'mira_operator_session'


def hdr(origin, cookie=None, token=None):
    return {'Origin':origin, **({'Cookie':COOKIE+'='+cookie} if cookie else {}),
        **({'X-Mira-Session-Token':token} if token else {})}


def bootstrap(client, origin):
    client.cookies.clear()
    response=client.post(origin+'/api/v1/devices/bootstrap',headers=hdr(origin))
    assert response.status_code==204,response.text
    return client.cookies.get(COOKIE)


def new_session(client, origin, cookie):
    client.cookies.clear()
    response=client.post(origin+'/api/v1/sessions',headers=hdr(origin,cookie),json={'client_instance_id':str(uuid4())})
    assert response.status_code==201,response.text
    return response.json()


def prepare(monkeypatch):
    monkeypatch.setattr(cli,'_prepare_frontend',lambda:None)
    monkeypatch.setattr(cli,'_generation',lambda *_:NativeGeneration())
    monkeypatch.setattr(cli,'_subscription_credentials',lambda *_:pytest.fail('no auth reads'))
    monkeypatch.setattr('tools.lan_discovery.discover_lan_address',lambda:SimpleNamespace(address='192.168.2.13',reason='selected',candidates=('192.168.2.13',)))


def test_default_serve_keeps_local_origin_and_admits_more_than_two_browsers(tmp_path,monkeypatch):
    prepare(monkeypatch)
    from tools import live_voice
    monkeypatch.setattr(live_voice,'_run_uvicorn',lambda *_a,**_kw:pytest.fail('default must compose exact local and LAN listeners'))
    def run(app,options):
        assert options.loopback_port==8000
        assert options.max_devices==16
        with TestClient(app,base_url=LAN) as client:
            cookies=[bootstrap(client,LAN) for _ in range(3)]
            sessions=[new_session(client,LAN,cookie) for cookie in cookies]
            local=bootstrap(client,LOCAL); local_session=new_session(client,LOCAL,local)
            assert len({s['session']['session_id'] for s in sessions+[local_session]})==4
            assert client.get(LOCAL+'/api/v1/sessions/'+local_session['session']['session_id'],
                headers=hdr(LAN,cookies[0],local_session['session_token'])).status_code==403
            assert app.state.usage_declaration.codex_requests==3
            assert app.state.container.settings.runtime.max_sessions==16
            assert client.get(LAN+'/api/v1/voice-capabilities',headers=hdr(LAN,cookies[0])).json()['microphone_enabled'] is False
    monkeypatch.setattr(access,'run_private_server',run)
    assert cli.main(args(env(tmp_path),'serve')+['--authorize-provider-data','--generation-requests','3'])==0


def test_default_voice_stays_local_and_private_actor_cannot_upgrade(tmp_path,monkeypatch):
    prepare(monkeypatch)
    from mira.bootstrap.providers import GoogleVoiceProviders
    from tests.integration.test_voice_http import Tts,Stt
    tts,stt=Tts(),Stt(); calls=[]
    async def closed(): calls.append('closed')
    def voice(): calls.append('voice-created');return GoogleVoiceProviders(stt,tts,closed)
    monkeypatch.setattr(cli,'_voice_factory',lambda *_:(voice,None))
    adc=tmp_path/'synthetic-adc.json';adc.write_text('{}');adc.chmod(0o600)
    path=env(tmp_path,'MIRA_SERVICES__SPEECH__PROJECT_ID=synthetic-project\nMIRA_SERVICES__SPEECH__TTS_VOICE=Kore\n')
    def run(app,options):
        with TestClient(app,base_url=LAN) as client:
            phone=bootstrap(client,LAN); first=new_session(client,LAN,phone)
            local=bootstrap(client,LOCAL); second=new_session(client,LOCAL,local)
            private_actor=app.state.container.sessions.get(first['session']['session_id'],first['session_token'])
            local_actor=app.state.container.sessions.get(second['session']['session_id'],second['session_token'])
            assert private_actor._speech_synthesis is None and private_actor._speech_recognition is None
            assert local_actor._speech_synthesis is tts and local_actor._speech_recognition is stt
            assert client.get(LAN+'/api/v1/voice-capabilities',headers=hdr(LAN,phone)).json()['speech_enabled'] is False
            assert client.get(LOCAL+'/api/v1/voice-capabilities',headers=hdr(LOCAL,local)).json()['microphone_enabled'] is True
            route='/api/v1/sessions/'+first['session']['session_id']
            response=client.post(LAN+route+'/response-preference',headers=hdr(LAN,phone,first['session_token']),
                json={'muted':False,'expected_revision':first['session']['revision']})
            assert response.status_code==403
            assert client.post(LAN+route+'/speech/'+str(uuid4())+'/stream',headers=hdr(LAN,phone,first['session_token']),json={}).status_code==403
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(LAN.replace('http:','ws:')+route+'/microphone',headers=hdr(LAN,phone)):pass
            # LAN socket with forged loopback authority cannot borrow local voice.
            assert client.get(LAN+'/api/v1/voice-capabilities',headers={**hdr(LOCAL,local),'Host':'127.0.0.1:8000'}).status_code==403
            assert calls==['voice-created'] and not tts.calls
        assert calls==['voice-created','closed']
    monkeypatch.setattr(access,'run_private_server',run)
    assert cli.main(args(path,'serve')+['--authorize-provider-data','--voice','--adc-file',str(adc),
        '--authorize-google-voice-data-and-spend'])==0


@pytest.mark.parametrize('reason',['none','ambiguous','unsupported'])
def test_uncertain_discovery_warns_and_preserves_loopback(tmp_path,monkeypatch,reason,capsys):
    prepare(monkeypatch)
    monkeypatch.setattr('tools.lan_discovery.discover_lan_address',lambda:SimpleNamespace(address=None,reason=reason,candidates=()))
    from tools import live_voice
    seen=[]
    monkeypatch.setattr(live_voice,'_run_uvicorn',lambda app,**kw:seen.append(app))
    monkeypatch.setattr(access,'run_private_server',lambda *_:pytest.fail('uncertain selection must not expose LAN'))
    assert cli.main(args(env(tmp_path),'serve')+['--authorize-provider-data'])==0
    assert len(seen)==1 and seen[0].state.operator_pairing is None
    output=capsys.readouterr()
    assert '局域网未启用，仅本机' in output.err and '--private-bind' in output.err
    assert 'http://127.0.0.1:8000' in output.out


def test_check_and_loopback_only_do_not_discover_network(tmp_path,monkeypatch,capsys):
    import json
    prepare(monkeypatch)
    monkeypatch.setattr('tools.lan_discovery.discover_lan_address',lambda:pytest.fail('no discovery'))
    assert cli.main(args(env(tmp_path)))==0
    report=json.loads(capsys.readouterr().out)
    assert report['device_access']['address_selection']=='on_serve'
    from tools import live_voice
    seen=[]
    monkeypatch.setattr(live_voice,'_run_uvicorn',lambda app,**kw:seen.append(app))
    assert cli.main(args(env(tmp_path),'serve')+['--authorize-provider-data','--loopback-only'])==0
    assert len(seen)==1


def test_text_actor_state_and_local_microphone_websocket_remain_correct(tmp_path,monkeypatch):
    prepare(monkeypatch)
    from mira.bootstrap.providers import GoogleVoiceProviders
    from tests.integration.test_voice_http import Tts,Stt
    async def closed():pass
    monkeypatch.setattr(cli,'_voice_factory',lambda *_:(lambda:GoogleVoiceProviders(Stt(),Tts(),closed),None))
    adc=tmp_path/'synthetic-adc.json';adc.write_text('{}');adc.chmod(0o600)
    path=env(tmp_path,'MIRA_SERVICES__SPEECH__PROJECT_ID=synthetic-project\nMIRA_SERVICES__SPEECH__TTS_VOICE=Kore\n')
    def run(app,options):
        with TestClient(app,base_url=LAN) as client:
            phone=bootstrap(client,LAN); first=new_session(client,LAN,phone)
            assert first['session']['response_mode']=='text_only'
            local=bootstrap(client,LOCAL); second=new_session(client,LOCAL,local)
            route='/api/v1/sessions/'+second['session']['session_id']+'/microphone'
            with client.websocket_connect(LOCAL.replace('http:','ws:')+route,headers=hdr(LOCAL,local)) as ws:
                # Reaching accept proves both outer listener and inner route allow the local origin.
                ws.close()
    monkeypatch.setattr(access,'run_private_server',run)
    assert cli.main(args(path,'serve')+['--authorize-provider-data','--voice','--adc-file',str(adc),
        '--authorize-google-voice-data-and-spend'])==0


@pytest.mark.parametrize('field',['memory_db','story_db','conversation_db'])
def test_existing_persistence_stays_loopback_but_explicit_lan_is_rejected(tmp_path,monkeypatch,field):
    command=args(env(tmp_path),'serve')
    parsed=cli._parser().parse_args(command)
    setattr(parsed,field,tmp_path/'synthetic.db')
    monkeypatch.setattr('tools.lan_discovery.discover_lan_address',lambda:pytest.fail('private persistence must not discover LAN'))
    assert access.resolve_serve_access(parsed) is None
    parsed.private_bind='192.168.2.13'
    with pytest.raises(access.PrivateDeviceError,match='persistent'):
        access.resolve_serve_access(parsed)


@pytest.mark.parametrize('fail_second',[False,True])
def test_exact_socket_bindings_precede_one_server_and_partial_failure_closes_all(monkeypatch,fail_second):
    import socket,uvicorn
    events=[];sockets=[]
    class Socket:
        def __init__(self,*_):sockets.append(self);self.closed=False
        def setsockopt(self,*_):pass
        def bind(self,address):
            events.append(('bind',address))
            if fail_second and len(sockets)==2:raise OSError('synthetic unavailable interface')
        def listen(self,*_):pass
        def setblocking(self,*_):pass
        def close(self):self.closed=True
    class Server:
        def __init__(self,config):
            assert config.workers==1 and config.proxy_headers is False
            assert config.lifespan=='auto'
            events.append('one-server')
        def run(self,*,sockets):
            assert len(sockets)==2
            events.append('one-run')
    monkeypatch.setattr(socket,'socket',Socket)
    monkeypatch.setattr(uvicorn,'Server',Server)
    options=SimpleNamespace(loopback_port=8000,host='192.168.2.13',port=8000)
    if fail_second:
        with pytest.raises(OSError):access.run_private_server(object(),options)
        assert 'one-server' not in events
    else:
        access.run_private_server(object(),options)
        assert events[-2:]==['one-server','one-run']
    assert events[:2]==[('bind',('127.0.0.1',8000)),('bind',('192.168.2.13',8000))]
    assert len(sockets)==2 and all(sock.closed for sock in sockets)


def test_lan_text_generation_uses_shared_request_budget_without_tts(tmp_path,monkeypatch):
    from tests.contracts.test_development_app_entry import wait_ready
    from tests.contracts.test_direct_codex_responses import backend,response
    from tests.contracts.test_direct_luna_tools import wire,message
    async def handle(request):return response(wire([message('Synthetic shared budget reply.')]))
    generation,synthetic_credentials,requests=backend(handle,request_limit=2)
    prepare(monkeypatch)
    monkeypatch.setattr(cli,'_generation',lambda *_:generation)
    def run(app,options):
        with TestClient(app,base_url=LAN) as client:
            for index,origin in enumerate((LAN,LOCAL,LAN)):
                cookie=bootstrap(client,origin); session=new_session(client,origin,cookie)
                path=origin+'/api/v1/sessions/'+session['session']['session_id']
                response=client.post(path+'/inputs',headers=hdr(origin,cookie,session['session_token']),
                    json={'request_id':str(uuid4()),'activity_seq':1,'presentation_cutoff':0,'text':'Synthetic text.'})
                assert response.status_code==202
                result=wait_ready(client,path,hdr(origin,cookie,session['session_token']))
                if index<2: assert result['active_grants'] and result['last_error'] is None
                else: assert result['last_error'] is not None
            assert len(requests)==synthetic_credentials.calls==2
    monkeypatch.setattr(access,'run_private_server',run)
    assert cli.main(args(env(tmp_path),'serve')+['--authorize-provider-data','--generation-requests','2'])==0
