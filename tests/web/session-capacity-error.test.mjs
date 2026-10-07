import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const dist = process.env.MIRA_TEST_WEB_DIST
  ? pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST) + '/').href
  : new URL('../../apps/web/dist/', import.meta.url).href;
const {MiraApiClient, MiraHttpError} = await import(new URL('features/session/api-client.js', dist));

const session = {
  schema_version: '0.1.0-foundation', session_id: 's', client_instance_id: 'c',
  revision: 0, activity_seq: 0, input_epoch: 0, output_epoch: 0, permit_revision: 0,
  phase: 'idle', request_id: null, sealed: false, active_grants: [], presented_effects: [],
  audio_progress: [], last_error: null,
};
const created = () => new Response(JSON.stringify({session, session_token: 'capability-secret'}), {
  headers: {'content-type': 'application/json'},
});
const requestId = '12345678-1234-4234-8234-123456789abc';

async function submitInputWith(errorResponse) {
  const api = new MiraApiClient({apiBase: '/api/v1', pollIntervalMs: 200}, {
    fetch: async (url, options) => {
      if (url === '/api/v1/sessions' && options.method === 'POST') return created();
      if (url.endsWith('/inputs')) return errorResponse;
      if (options.method === 'DELETE') return new Response(null, {status: 204});
      throw new Error(`Unexpected request: ${options.method} ${url}`);
    },
  });
  await api.create('c');
  try {
    await api.input({});
  } catch (error) {
    await api.close();
    return error;
  }
  await api.close();
  throw new Error('Expected the input request to fail');
}

function jsonError(code, message, headers = {}) {
  return new Response(JSON.stringify({code, message, request_id: requestId}), {
    status: 429, headers: {'content-type': 'application/json', 'x-request-id': requestId, ...headers},
  });
}

test('MiraApiClient gives a local recovery action only for exact 429 session_capacity', async () => {
  const error = await submitInputWith(jsonError('session_capacity', 'untrusted server message'));
  assert.ok(error instanceof MiraHttpError);
  assert.equal(error.status, 429);
  assert.equal(error.code, 'session_capacity');
  assert.match(error.message, /本地会话达到容量限制/);
  assert.match(error.message, /结束当前或不用的会话/);
  assert.match(error.message, /重复提交本轮不会解除限制/);
  assert.match(error.message, new RegExp(requestId));
  assert.doesNotMatch(error.message, /untrusted server message|配额/);
});

test('capacity detail is not inferred from another status, code, malformed, or oversized response', async () => {
  const genericCases = [
    [jsonError('Session_capacity', 'do not reflect me'), /稍后重试或检查配额/],
    [jsonError('provider_quota', 'do not reflect me'), /稍后重试或检查配额/],
    [new Response(JSON.stringify({code: 'session_capacity', message: 'do not reflect me'}), {
      status: 409, headers: {'content-type': 'application/json', 'x-request-id': requestId},
    }), /操作与当前会话状态冲突/],
    [new Response(JSON.stringify({code: 'session_capacity', message: 'do not reflect me'}), {
      status: 503, headers: {'content-type': 'application/json', 'x-request-id': requestId},
    }), /服务暂不可用/],
    [new Response('<html>do not reflect me</html>', {
      status: 429, headers: {'content-type': 'text/html', 'x-request-id': requestId},
    }), /稍后重试或检查配额/],
    [new Response(JSON.stringify({code: 'session_capacity', message: 'do not reflect me'}), {
      status: 429, headers: {'content-type': 'text/html', 'x-request-id': requestId},
    }), /稍后重试或检查配额/],
    [new Response('{"code":"session_capacity",', {
      status: 429, headers: {'content-type': 'application/json', 'x-request-id': requestId},
    }), /稍后重试或检查配额/],
    [new Response(JSON.stringify({code: 'session_capacity', message: 'do not reflect me'}), {
      status: 429, headers: {'content-type': 'application/json', 'content-length': '4097', 'x-request-id': requestId},
    }), /稍后重试或检查配额/],
    [new Response(' '.repeat(4097) + JSON.stringify({code: 'session_capacity'}), {
      status: 429, headers: {'content-type': 'application/json', 'x-request-id': requestId},
    }), /稍后重试或检查配额/],
  ];
  for (const [response, expectedGeneric] of genericCases) {
    const error = await submitInputWith(response);
    assert.ok(error instanceof MiraHttpError);
    assert.equal(error.code, null);
    assert.match(error.message, expectedGeneric);
    assert.match(error.message, new RegExp(requestId));
    assert.doesNotMatch(error.message, /本地会话达到容量限制|do not reflect me|<html>/);
  }
});

test('untrusted server message never replaces static capacity text and invalid correlation is omitted', async () => {
  const error = await submitInputWith(new Response(JSON.stringify({code: 'session_capacity', message: 'Bearer reflected-secret'}), {
    status: 429, headers: {'content-type': 'application/json', 'x-request-id': 'Bearer synthetic-secret'},
  }));
  assert.ok(error instanceof MiraHttpError);
  assert.equal(error.code, 'session_capacity');
  assert.match(error.message, /本地会话达到容量限制/);
  assert.doesNotMatch(error.message, /Bearer|synthetic-secret|reflected-secret/);
  assert.doesNotMatch(error.message, /诊断编号/);
});
