"""Actual CLI -> direct bootstrap -> lifespan with injected, offline providers."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from tools import live_provider as cli
from tools import private_device_access as access
from tests.contracts.test_live_provider_launcher import arguments, env
from tests.contracts.test_luna_native_bootstrap import NativeGeneration

ORIGIN = 'http://192.168.2.13:8000'
FLAG = '--trusted-private-network-no-pairing'
COOKIE = 'mira_operator_session'


def command(tmp_path, mode='serve', trusted=True):
    return arguments(env(tmp_path), mode) + ['--private-bind', '192.168.2.13',
        '--device-origin', ORIGIN, '--allow-private-http-text', '--authorize-provider-data',
        '--generation-requests', '3', '--turns', '4'] + ([FLAG] if trusted else ['--require-device-pairing'])


def headers(cookie=None, token=None):
    return {'Origin': ORIGIN, **({'Cookie': COOKIE+'='+cookie} if cookie else {}),
        **({'X-Mira-Session-Token': token} if token else {})}


def boot(client, cookie=None):
    client.cookies.clear()
    response = client.post('/api/v1/devices/bootstrap', headers=headers(cookie))
    assert response.status_code == 204, response.text
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    return client.cookies.get(COOKIE)


def create(client, cookie, instance):
    client.cookies.clear()
    response = client.post('/api/v1/sessions', headers=headers(cookie),
        json={'client_instance_id': instance})
    assert response.status_code == 201, response.text
    return response.json()


def test_full_cli_two_browsers_refresh_restart_and_default_pairing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, '_prepare_frontend', lambda: None)
    monkeypatch.setattr(cli, '_generation', lambda *_: NativeGeneration())
    monkeypatch.setattr(cli, '_subscription_credentials', lambda *_: pytest.fail('No auth reads'))
    previous = []
    def run(app, options):
        assert options.host == '192.168.2.13'
        assert app.state.container is None
        with TestClient(app, base_url=ORIGIN) as client:
            assert client.post('/api/v1/sessions', headers=headers(),
                json={'client_instance_id': str(uuid4())}).status_code == 401
            phone = boot(client, previous[-1] if previous else None)
            if previous: assert phone != previous[-1]
            previous.append(phone)
            desktop = boot(client)
            assert phone != desktop
            assert boot(client, phone) == phone
            instance = str(uuid4())
            first = create(client, phone, instance); second = create(client, desktop, instance)
            container = app.state.container
            one = '/api/v1/sessions/'+first['session']['session_id']
            two = '/api/v1/sessions/'+second['session']['session_id']
            assert one != two
            assert client.get(one, headers=headers(desktop, first['session_token'])).status_code == 403
            with pytest.raises(WebSocketDisconnect) as caught:
                with client.websocket_connect(one+'/continuous-listening', headers=headers(desktop)): pass
            assert caught.value.code == 4403
            fresh = create(client, phone, instance)
            assert fresh['session']['session_id'] != first['session']['session_id']
            assert client.get(two, headers=headers(desktop, second['session_token'])).status_code == 200
            assert app.state.container is container
            for _ in range(14): boot(client)
            client.cookies.clear()
            assert client.post('/api/v1/devices/bootstrap', headers=headers()).status_code == 429
            assert client.post('/api/v1/devices/bootstrap', headers={'Origin':'http://evil.invalid'}).status_code == 403
            assert client.post('/api/v1/devices/bootstrap', headers={**headers(),'Host':'evil.invalid'}).status_code == 403
            assert client.post('/api/v1/devices/bootstrap').status_code == 403
            assert client.post('/api/v1/operator/pair', headers=headers(), json={'code':'unused'}).status_code != 204
            assert app.state.usage_declaration.codex_requests == 3
            page = client.get('/').text
            assert 'data-device-access="trusted-private-network-no-pairing"' in page
            assert '可信局域网免配对' in page
            assert 'data-operator-pairing="required"' not in page
            assert client.post('/api/v1/devices/revoke', headers=headers(phone)).status_code == 204
            assert client.get(two, headers=headers(desktop, second['session_token'])).status_code == 200
            assert boot(client) not in (phone, desktop)
        assert not app.state.container.sessions._sessions
    monkeypatch.setattr(access, 'run_private_server', run)
    assert cli.main(command(tmp_path)) == 0
    assert cli.main(command(tmp_path)) == 0
    assert cli.main(command(tmp_path, trusted=False)) == 2


def test_check_no_pairing_directory_or_provider_construction(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('No providers in check'))
    assert cli.main(command(tmp_path, 'check')) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['device_access']['pairing_required'] is False
    assert result['device_access']['max_device_sessions'] == 16
    assert result['generation_request_limit'] == 3
    assert result['device_access']['pairing_files_created'] is False


@pytest.mark.parametrize('extra', [[], ['--private-bind','0.0.0.0'], ['--private-bind','8.8.8.8'],
    ['--device-pairing-dir','/tmp'], ['--voice'], ['--memory-db','/tmp/synthetic.db'],
    ['--story-db','/tmp/synthetic.db'], ['--conversation-db','/tmp/synthetic.db']])
def test_unsafe_or_ambiguous_modes_fail_before_provider_creation(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(cli, '_generation', lambda *_: pytest.fail('No providers'))
    argv = command(tmp_path, 'check')
    if not extra:
        argv = arguments(env(tmp_path)) + [FLAG]
    assert cli.main(argv + extra) == 2


def test_default_cli_still_creates_two_one_use_files_and_requires_manual_pairing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, '_prepare_frontend', lambda: None)
    monkeypatch.setattr(cli, '_generation', lambda *_: NativeGeneration())
    directory = tmp_path / 'default-pairing'
    directory.mkdir(mode=0o700)
    def run(app, options):
        assert not options.trusted_no_pairing
        files = list(directory.iterdir())
        assert len(files) == 2
        codes = [path.read_text().strip() for path in files]
        assert codes[0] != codes[1]
        with TestClient(app, base_url=ORIGIN) as client:
            assert app.state.container is None
            assert client.post('/api/v1/devices/bootstrap', headers=headers()).status_code != 204
            page = client.get('/').text
            assert 'data-operator-pairing="required"' in page
            assert 'data-device-access="private"' in page
            assert client.post('/api/v1/operator/pair', headers=headers(), json={'code':codes[0]}).status_code == 204
            first = client.cookies.get(COOKIE)
            assert client.post('/api/v1/operator/pair', headers=headers(), json={'code':codes[0]}).status_code == 401
            assert client.post('/api/v1/operator/pair', headers=headers(), json={'code':codes[1]}).status_code == 204
            second = client.cookies.get(COOKIE)
            assert first != second
            assert create(client, first, str(uuid4()))['session']['session_id'] != create(client, second, str(uuid4()))['session']['session_id']
        assert all(code not in capsys.readouterr().out for code in codes)
    monkeypatch.setattr(access, 'run_private_server', run)
    assert cli.main(command(tmp_path, trusted=False) + ['--device-pairing-dir', str(directory)]) == 0


def test_expired_browser_cannot_use_old_token_and_fresh_admission_reclaims_only_its_slot(tmp_path, monkeypatch):
    from mira.entrypoints.http import trusted_device_access
    from types import SimpleNamespace
    now = [100.0]
    monkeypatch.setattr(trusted_device_access, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(cli, '_prepare_frontend', lambda: None)
    monkeypatch.setattr(cli, '_generation', lambda *_: NativeGeneration())
    def run(app, options):
        with TestClient(app, base_url=ORIGIN) as client:
            phone = boot(client); first = create(client, phone, str(uuid4()))
            now[0] += 100
            desktop = boot(client); second = create(client, desktop, str(uuid4()))
            now[0] = 100.0 + 28_801
            path = '/api/v1/sessions/'+first['session']['session_id']
            denied = client.get(path, headers=headers(phone, first['session_token']))
            assert denied.status_code == 401
            assert '刷新' in denied.json()['message']
            assert 'Pair' not in denied.json()['message']
            replacement = boot(client, phone)
            assert replacement != phone
            assert first['session']['session_id'] not in app.state.container.sessions._sessions
            assert client.get('/api/v1/sessions/'+second['session']['session_id'],
                headers=headers(desktop, second['session_token'])).status_code == 200
    monkeypatch.setattr(access, 'run_private_server', run)
    assert cli.main(command(tmp_path)) == 0
