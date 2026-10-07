from __future__ import annotations
import gzip
import json
import zlib

import httpx
import pytest
from mira.adapters.auth import openai_codex as m

SECRET = 'synthetic-secret-body-header-code-token'
BODY = json.dumps({'device_auth_id':SECRET,'user_code':'SYNTHETIC','interval':0}).encode()

class RawStream(httpx.SyncByteStream):
    def __init__(self, raw): self.raw = raw
    def __iter__(self): yield self.raw

@pytest.mark.parametrize('encoding,wire', [
    ('gzip', gzip.compress(BODY)), ('deflate', zlib.compress(BODY)),
    ('identity', BODY), (None, BODY),
])
def test_valid_response_is_decoded_exactly_once(tmp_path, encoding, wire):
    seen = []
    def handler(request):
        seen.append(request)
        headers = {'content-length':str(len(wire)), 'x-private':SECRET}
        if encoding: headers['content-encoding'] = encoding
        return httpx.Response(200, headers=headers, stream=RawStream(wire), request=request)
    store = m.CodexSessionStore(tmp_path / 'unopened' / 'session.json', transport=httpx.MockTransport(handler))
    result = store._post_json(m.CODEX_DEVICE_CODE_URL, json_body={'client_id':m.CODEX_OAUTH_CLIENT_ID})
    assert result.content == BODY
    assert json.loads(result.content)['device_auth_id'] == SECRET
    assert 'content-encoding' not in result.headers
    assert 'transfer-encoding' not in result.headers
    assert result.headers['content-length'] == str(len(BODY))
    assert len(seen) == 1
    assert seen[0].headers['accept-encoding'] == 'identity'
    assert not store.path.parent.exists()


def test_invalid_gzip_does_not_retry_or_fallback(tmp_path):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, headers={'content-encoding':'gzip','content-length':str(len(BODY)), 'x-private':SECRET}, stream=RawStream(BODY), request=request)
    store = m.CodexSessionStore(tmp_path / 'unopened' / 'session.json', transport=httpx.MockTransport(handler))
    with pytest.raises(m.CodexAuthError) as caught:
        store.begin_device_login(on_user_code=lambda *_: pytest.fail('never expose code'))
    diagnostic = caught.value.safe_diagnostic()
    assert diagnostic['content_encoding'] == 'gzip'
    assert diagnostic['content_length_bucket'] == 'small_1_4096'
    assert diagnostic['decoded_bytes_bucket'] == 'empty'
    assert diagnostic['phase'] == 'response_body'
    assert diagnostic['http_status'] == 200
    assert 'response_decoding' in diagnostic['categories']
    assert SECRET not in json.dumps(diagnostic)
    assert len(seen) == 1 and not store.path.parent.exists()


@pytest.mark.parametrize('encoding', ['br','zstd'])
def test_optional_decoder_failure_is_safe_without_optional_install(monkeypatch,tmp_path,encoding):
    # Deterministic failure seam exercises HTTPX's optional-decoder boundary;
    # does not claim real codec execution if optional dependencies are absent.
    seen=[]
    original = httpx.Response.iter_bytes
    def iter_bytes(response, *args, **kwargs):
        if response.headers.get('content-encoding') == encoding:
            raise httpx.DecodingError(SECRET)
        yield from original(response,*args,**kwargs)
    monkeypatch.setattr(httpx.Response,'iter_bytes',iter_bytes)
    def handler(request):
        seen.append(request)
        return httpx.Response(200,headers={'content-encoding':encoding},stream=RawStream(b'bad'),request=request)
    store = m.CodexSessionStore(tmp_path/'unopened'/'session.json',transport=httpx.MockTransport(handler))
    with pytest.raises(m.CodexAuthError) as caught: store.begin_device_login()
    diagnostic=caught.value.safe_diagnostic()
    assert diagnostic['content_encoding'] == encoding
    assert diagnostic['phase'] == 'response_body'
    assert SECRET not in json.dumps(diagnostic)
    assert len(seen)==1 and not store.path.parent.exists()


@pytest.mark.parametrize('raw,expected', [('gzip','gzip'),(' GZip ','gzip'),('gzip, br','multiple'),(SECRET,'other'),('', 'none'),(None,'none')])
def test_encoding_classification_fixed(raw,expected):
    assert m._safe_content_encoding(raw) == expected


@pytest.mark.parametrize('raw,expected', [('0','empty'),('4096','small_1_4096'),('4097','medium_4097_65536'),('65537','large_65537_1048576'),('1048577','over_limit'),('9'*9000,'unknown'),(SECRET,'unknown'),('-1','unknown'),(None,'unknown')])
def test_content_length_is_bucket_only(raw,expected):
    assert m._safe_content_length_bucket(raw)==expected


def test_unknown_metadata_filtered_again_at_cli_boundary():
    error=m.CodexAuthError('oauth_network_error',diagnostic={'content_encoding':SECRET,'content_length_bucket':SECRET,'decoded_bytes_bucket':SECRET})
    assert SECRET not in json.dumps(error.safe_diagnostic())


def test_real_login_with_valid_gzip_each_stage(monkeypatch,tmp_path):
    seen=[]
    def handler(request):
        seen.append(request)
        if len(seen)==1: payload={'device_auth_id':SECRET,'user_code':'SYNTHETIC','interval':0}
        elif len(seen)==2: payload={'authorization_code':SECRET,'code_verifier':SECRET}
        else: payload={'access_token':SECRET,'refresh_token':SECRET,'expires_in':3600}
        raw=gzip.compress(json.dumps(payload).encode())
        return httpx.Response(200,headers={'content-encoding':'gzip','content-length':str(len(raw))},stream=RawStream(raw),request=request)
    store=m.CodexSessionStore(tmp_path/'mira'/'session.json',transport=httpx.MockTransport(handler),sleep=lambda _:None)
    shown=[]
    store.begin_device_login(on_user_code=lambda url,code:shown.append(code))
    assert shown==['SYNTHETIC'] and len(seen)==3
    assert store.status()
    assert all(req.headers['accept-encoding']=='identity' for req in seen)
