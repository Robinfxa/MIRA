import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mira.config.loader import ConfigurationError
from mira.config.settings import ProviderSettings, Settings
from mira.entrypoints.http.app import create_app


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as value: yield value


def create(client):
    response=client.post("/api/v1/sessions",json={"client_instance_id":str(uuid4())})
    assert response.status_code==201
    data=response.json()
    return "/api/v1/sessions/"+data["session"]["session_id"], {"X-Mira-Session-Token":data["session_token"]}


def ready(client,path,headers):
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        response=client.get(path,headers=headers)
        data=response.json()
        if data["sealed"] or data["phase"]=="error": return data
        time.sleep(.005)
    raise AssertionError("Mock did not finish")


def test_health_reports_mock_truthfully(client):
    data=client.get("/api/v1/health").json()
    assert data["mode"]=="mock" and not data["live_audio"] and not data["live_images"]


def test_session_capability_required(client):
    path,headers=create(client)
    assert client.get(path,headers={"X-Mira-Session-Token":"wrong"}).status_code==404
    assert client.get(path).status_code==422


def test_session_isolation(client):
    path1,headers1=create(client);path2,headers2=create(client)
    assert client.get(path1,headers=headers2).status_code==404
    assert client.get(path2,headers=headers1).status_code==404


def test_input_to_permit_to_receipt_and_stop(client):
    path,headers=create(client)
    data={"request_id":str(uuid4()),"activity_seq":1,"presentation_cutoff":0,"text":"不要拍我"}
    assert client.post(path+"/inputs",json=data,headers=headers).status_code==202
    state=ready(client,path,headers);effect=state["active_grants"][0]
    assert state["phase"]=="ready" and not state["presented_effects"]
    receipt={"effect_id":effect["id"],"digest":effect["digest"],"output_epoch":1,
             "activity_seq":1,"presentation_seq":1}
    result=client.post(path+"/receipts",json=receipt,headers=headers)
    assert result.status_code==200 and result.json()["phase"]=="idle"
    stopped=client.post(path+"/stop",json={"activity_seq":2,"presentation_cutoff":1},headers=headers).json()
    assert stopped["active_grants"]==[] and len(stopped["presented_effects"])==1
    assert client.post(path+"/receipts",json=receipt,headers=headers).status_code==200


@pytest.mark.parametrize("patch",[{"text":"  "},{"activity_seq":-1},{"activity_seq":"1"},{"surprise":True},{"text":"x"*2001}])
def test_invalid_input_rejected(client,patch):
    path,headers=create(client)
    body={"request_id":str(uuid4()),"activity_seq":1,"presentation_cutoff":0,"text":"hello"}|patch
    response=client.post(path+"/inputs",json=body,headers=headers)
    assert response.status_code==422 and response.json()["code"]=="invalid_request"


def test_origin_not_allowed(client):
    assert client.post("/api/v1/sessions",json={"client_instance_id":str(uuid4())},
                       headers={"Origin":"https://hostile.example"}).status_code==403


def test_public_config_does_not_expose_credentials(client):
    response=client.get("/api/v1/health")
    assert "api_key" not in response.text and "session_token" not in response.text
    assert client.get("/.env").status_code==404
    assert client.get("/config/defaults.toml").status_code==404


def test_delete_releases_session(client):
    path,headers=create(client)
    assert client.delete(path,headers=headers).status_code==204
    assert client.get(path,headers=headers).status_code==404


def test_audit_omits_user_text_and_token(client):
    path,headers=create(client)
    client.post(path+"/inputs",json={"request_id":str(uuid4()),"activity_seq":1,
                 "presentation_cutoff":0,"text":"private-test-phrase"},headers=headers)
    ready(client,path,headers)
    response=client.get(path+"/events",headers=headers)
    assert response.status_code==200
    assert "private-test-phrase" not in response.text
    assert headers["X-Mira-Session-Token"] not in response.text


def test_live_selection_fails_at_startup_not_silently_mock():
    with pytest.raises(ConfigurationError):
        with TestClient(create_app(Settings(providers=ProviderSettings(generation="api")))):
            pass


def test_unexpected_body_is_not_echoed(client):
    response=client.post("/api/v1/sessions",json={"client_instance_id":"do-not-reflect"})
    assert "do-not-reflect" not in response.text


def test_large_control_body_rejected(client):
    assert client.post("/api/v1/sessions",content="x"*40000,
                       headers={"Content-Type":"application/json"}).status_code==413
