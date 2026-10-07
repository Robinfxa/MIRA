import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import vm from 'node:vm';

const dist = process.env.MIRA_TEST_WEB_DIST ? resolve(process.env.MIRA_TEST_WEB_DIST) : resolve('apps/web/dist');
const {mountOperatorPairing} = await import(resolve(dist, 'features/session/operator-pairing.js')); 
const markup = await readFile(new URL('../../apps/web/index.html', import.meta.url), 'utf8');
const mainSource = await readFile(resolve(dist, 'app/main-source.js'), 'utf8');
const pairingSource = await readFile(new URL('../../apps/web/src/features/session/operator-pairing.ts', import.meta.url), 'utf8');

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}

class FakeElement {
  listeners = new Map();
  value = '';
  textContent = '';
  hidden = false;
  disabled = false;
  addEventListener(name, listener) {
    const list = this.listeners.get(name) ?? [];
    list.push(listener); this.listeners.set(name, list);
  }
  fire(name, extras = {}) {
    const event = {defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extras};
    for (const listener of this.listeners.get(name) ?? []) listener(event);
    return event;
  }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children = [...(this.children ?? []), ...children]; }
}

function pairingDom() {
  const nodes = new Map([
    ['[data-operator-pairing-panel]', new FakeElement()],
    ['[data-operator-pairing-form]', new FakeElement()],
    ['[data-operator-pairing-code]', new FakeElement()],
    ['[data-operator-pairing-submit]', new FakeElement()],
    ['[data-operator-pairing-status]', new FakeElement()],
    ['[data-operator-pairing-cancel]', new FakeElement()],
  ]);
  const window = new FakeElement();
  const document = {defaultView: window, querySelector: selector => nodes.get(selector) ?? null};
  return {document, nodes, window};
}

function response(status, jsonValue = null) {
  return {
    status,
    async json() { return jsonValue; },
    get body() { throw new Error('POST response body must not be inspected'); },
  };
}

const statusResponse = paired => response(200, {required: true, paired, revoked: false});
const tick = () => new Promise(resolve => setImmediate(resolve));

test('memory page marker gates controller startup; static page stays unmarked', async () => {
  assert.match(mainSource, /document\.body\?\.dataset\['operatorPairing'\] === 'required'/);
  assert.match(mainSource, /operatorGate = mountOperatorPairing\(document, \{\s*onPaired: startSessionApp\s*\}\)/);
  assert.doesNotMatch(markup, /<body[^>]*data-operator-pairing=/,
    'the backend injects the marker only into memory-mode HTML');
  assert.match(markup, /data-operator-pairing-code type="password"[^>]*autocomplete="off"/);
  assert.match(markup, /同一操作系统账户下的恶意软件/);
  assert.doesNotMatch(pairingSource, /\b(?:location|localStorage|sessionStorage|clipboard|console)\b/);
});

test('local-only pairing copy names only the local management capability', async () => {
  const dom = pairingDom();
  const {nodes} = dom;
  const fetcher = async (path, init) => {
    if (path === '/api/v1/operator/status') return response(200, {required: true, paired: false, revoked: false});
    if (path === '/api/v1/operator/pair') {
      assert.equal(JSON.parse(init.body).code, 'synthetic-browser-test-code');
      return response(204);
    }
    if (path === '/api/v1/operator/revoke') return response(204);
    throw new Error(`unexpected request ${path}`);
  };
  const gate = mountOperatorPairing(dom.document, {
    fetcher,
    localOnly: true,
    onPaired: () => ({async stopAndClose() {}}),
  });
  await gate.ready;
  nodes.get('[data-operator-pairing-code]').value = 'synthetic-browser-test-code';
  nodes.get('[data-operator-pairing-form]').fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.match(nodes.get('[data-operator-pairing-status]').textContent, /本机管理配对已确认/);
  assert.doesNotMatch(nodes.get('[data-operator-pairing-status]').textContent, /MIRA 服务|停止回应/);
  await gate.close();
});

test('marked main page constructs no private API, watcher, or controller until gate callback', async () => {
  const source = mainSource.replace(/^import .*;\n/gm, '');
  const nodes = new Map();
  const calls = [];
  let pairingOptions;
  let selectors = 0;
  class Node extends FakeElement {
    dataset = {};
    setAttribute(name, value) { this[name] = value; }
    setPointerCapture() {}
  }
  const document = {
    body: {dataset: {operatorPairing: 'required'}},
    visibilityState: 'visible',
    querySelector(selector) { selectors++; if (!nodes.has(selector)) nodes.set(selector, new Node()); return nodes.get(selector); },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
  const window = new Node();
  class Panel {
    recordingActive = false;
    setCanEnable() {}
    setContinuousListeningBlocked() {}
    start() {}
    close() {}
    invalidateForNewInput() {}
    invalidateForStop() {}
    auditionState() {}
  }
  class Controller {
    microphoneBusy = false;
    constructor() { calls.push('controller'); }
    connect() { calls.push('connect'); return Promise.resolve(); }
    stop() { return Promise.resolve(); }
    close() { return Promise.resolve(); }
    setContinuousListeningPhase() {}
  }
  class ContinuousListeningController {active=false;constructor(options){this.options=options;options.onUpdate({state:'idle',lease_id:null,ready:null,transcript:null,sent_text:[],notice:null,error:null});}start(){this.active=true;return true;}stop(){this.active=false;return Promise.resolve();}close(){this.active=false;return Promise.resolve();}sendCurrent(){return Promise.resolve();}}
  vm.runInNewContext(source, {
    document, window,
    globalThis: {AudioContext: class {}, AudioWorkletNode: class {}, isSecureContext: true},
    navigator: {mediaDevices: {getUserMedia() {}}}, isSecureContext: true,
    loadPublicConfig: () => ({}),
    watchDiagnosticsStatus() { calls.push('watch'); return {close() {}}; },
    recordingNotice: () => ({visible: false, text: '', state: 'off'}), safeSessionError: () => 'safe error',
    mountOperatorPairing(_doc, options) { calls.push('gate'); pairingOptions = options; return {cancelAndRevoke() {}}; },
    MiraApiClient: class { constructor() { calls.push('api'); } },
    SessionController: Controller, ReviewedAudioPanel: Panel, ContinuousListeningController,
    SceneEffectExecutor: class {},
  });
  assert.deepEqual(calls, ['gate']);
  assert.equal(selectors, 0, 'no private app DOM setup runs while unpaired');
  pairingOptions.onPaired();
  await tick();
  assert.deepEqual(calls, ['gate', 'watch', 'api', 'controller', 'connect']);
});

test('unpaired page only makes public status request; success requires exact 204 and clears code before sending', async () => {
  const dom = pairingDom();
  const pairRequest = deferred();
  const requests = [];
  let starts = 0;
  const fetcher = (url, init) => {
    requests.push({url, init});
    if (url.endsWith('/status')) return Promise.resolve(statusResponse(false));
    if (url.endsWith('/pair')) return pairRequest.promise;
    throw new Error(`unexpected endpoint ${url}`);
  };
  const gate = mountOperatorPairing(dom.document, {fetcher, onPaired: () => { starts++; }});
  await gate.ready;
  assert.equal(starts, 0, 'no private session is started before successful pairing');
  assert.deepEqual(requests.map(({url}) => url), ['/api/v1/operator/status']);
  assert.equal(requests[0].init.credentials, 'include');
  assert.equal(requests[0].init.cache, 'no-store');
  assert.equal('Origin' in requests[0].init.headers, false, 'browser supplies Origin; page does not spoof it');
  assert.equal('Authorization' in requests[0].init.headers, false, 'browser-owned cookie is never copied into headers');

  const input = dom.nodes.get('[data-operator-pairing-code]');
  input.value = 'synthetic-test-code';
  dom.nodes.get('[data-operator-pairing-form]').fire('submit');
  assert.equal(input.value, '', 'input is cleared synchronously before fetch settles');
  await tick();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].url, '/api/v1/operator/pair');
  assert.equal(requests[1].init.credentials, 'include');
  assert.equal('Origin' in requests[1].init.headers, false);
  assert.equal('Authorization' in requests[1].init.headers, false);
  assert.deepEqual(JSON.parse(requests[1].init.body), {code: 'synthetic-test-code'});
  assert.equal(starts, 0);
  dom.nodes.get('[data-operator-pairing-form]').fire('submit');
  assert.equal(requests.length, 2, 'double submission is fenced while the first request is pending');

  pairRequest.resolve(response(204));
  await tick();
  await tick();
  assert.equal(starts, 1);
  assert.equal(dom.nodes.get('[data-operator-pairing-code]').value, '');
});

test('HTTP failure never reads its body or produces a fake paired state', async () => {
  const dom = pairingDom();
  const requests = [];
  let starts = 0;
  const gate = mountOperatorPairing(dom.document, {
    fetcher: async (url, init) => {
      requests.push({url, init});
      return url.endsWith('/status') ? statusResponse(false) : response(401);
    },
    onPaired: () => { starts++; },
  });
  await gate.ready;
  dom.nodes.get('[data-operator-pairing-code]').value = 'synthetic-invalid-code';
  dom.nodes.get('[data-operator-pairing-form]').fire('submit');
  await tick();
  await tick();
  const message = dom.nodes.get('[data-operator-pairing-status]').textContent;
  assert.equal(starts, 0);
  assert.equal(dom.nodes.get('[data-operator-pairing-code]').value, '');
  assert.doesNotMatch(message, /synthetic-invalid-code/);
  assert.match(message, /不会自动重试/);
  assert.equal(requests.some(item => item.url.endsWith('/revoke')), false);
});

test('status accepts only the three contracted booleans and rejects unexpected fields', async () => {
  const dom = pairingDom();
  let starts = 0;
  const gate = mountOperatorPairing(dom.document, {
    fetcher: async () => response(200, {required: true, paired: true, revoked: false, secret: 'hidden'}),
    onPaired: () => { starts++; },
  });
  await gate.ready;
  assert.equal(starts, 0);
  assert.match(dom.nodes.get('[data-operator-pairing-status]').textContent, /不会启动记忆会话/);
});

test('revoked status requires a fresh local launch and cannot re-pair', async () => {
  const dom = pairingDom();
  const requests = [];
  let starts = 0;
  const gate = mountOperatorPairing(dom.document, {
    fetcher: async (url, init) => {
      requests.push({url, init});
      return response(200, {required: true, paired: false, revoked: true});
    }, onPaired: () => { starts++; },
  });
  await gate.ready;
  dom.nodes.get('[data-operator-pairing-form]').fire('submit');
  assert.equal(starts, 0);
  assert.deepEqual(requests.map(({url}) => url), ['/api/v1/operator/status']);
  assert.match(dom.nodes.get('[data-operator-pairing-status]').textContent, /重新启动本机 MIRA 服务/);
});

test('status response parsing stays inside the abort deadline', async () => {
  const dom = pairingDom();
  let starts = 0;
  const gate = mountOperatorPairing(dom.document, {
    deadlineMs: 20,
    fetcher: async (_url, init) => ({
      status: 200,
      json: () => new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => reject(new Error('deadline')), {once: true});
      }),
    }),
    onPaired: () => { starts++; },
  });
  await gate.ready;
  assert.equal(starts, 0);
  assert.equal(dom.nodes.get('[data-operator-pairing-form]').hidden, true);
  assert.match(dom.nodes.get('[data-operator-pairing-status]').textContent, /不会启动记忆会话/);
});

test('cancelling during late pair response cannot unlock UI and revokes after local closure', async () => {
  const dom = pairingDom();
  const latePair = deferred();
  const requests = [];
  const order = [];
  let starts = 0;
  const gate = mountOperatorPairing(dom.document, {
    fetcher: (url, init) => {
      requests.push({url, init});
      if (url.endsWith('/status')) return Promise.resolve(statusResponse(false));
      if (url.endsWith('/pair')) return latePair.promise;
      if (url.endsWith('/revoke')) { order.push('revoke'); return Promise.resolve(response(204)); }
      throw new Error('unexpected endpoint');
    }, onPaired: () => { starts++; order.push('started'); },
  });
  await gate.ready;
  dom.nodes.get('[data-operator-pairing-code]').value = 'synthetic-late-code';
  dom.nodes.get('[data-operator-pairing-form]').fire('submit');
  await tick();
  const cancellation = gate.cancelAndRevoke();
  latePair.resolve(response(204));
  await cancellation;
  await tick();
  assert.equal(starts, 0);
  assert.deepEqual(order, ['revoke']);
  assert.equal(requests.at(-1).url, '/api/v1/operator/revoke');
  assert.equal(requests.at(-1).init.credentials, 'include');
  assert.equal(dom.nodes.get('[data-operator-pairing-code]').value, '');
});

test('existing same-process app cookie is revoked only after local stop and close', async () => {
  const dom = pairingDom();
  const order = [];
  const gate = mountOperatorPairing(dom.document, {
    fetcher: async (url, init) => {
      order.push(`fetch:${url}`);
      return url.endsWith('/status') ? statusResponse(true) : response(204);
    },
    onPaired: () => ({stopAndClose: async () => { order.push('local-stop-close'); }}),
  });
  await gate.ready;
  assert.deepEqual(order, ['fetch:/api/v1/operator/status']);
  assert.equal(dom.nodes.get('[data-operator-pairing-form]').hidden, true);
  await gate.cancelAndRevoke();
  assert.deepEqual(order, [
    'fetch:/api/v1/operator/status', 'local-stop-close', 'fetch:/api/v1/operator/revoke',
  ]);
  assert.match(dom.nodes.get('[data-operator-pairing-status]').textContent, /配对已撤销/);
});

const upgradeCode = 'story_checkpoint_canon_upgrade_required';
function upgradeResponse(overrides = {}, status = 409, headers = {}) {
  return new Response(JSON.stringify({code: upgradeCode, message: 'UNTRUSTED_SECRET /private/database.sqlite3',
    request_id: 'synthetic-request', ...overrides}),
    {status, headers: {'Content-Type': 'application/json', ...headers}});
}
async function submitPairReply(reply, options = {}) {
  const dom = pairingDom();
  let starts = 0;
  const requests = [];
  const gate = mountOperatorPairing(dom.document, {deadlineMs: 200, ...options,
    fetcher: async (url, init) => {
      requests.push({url, init});
      if (url.endsWith('/status')) return statusResponse(false);
      if (url.endsWith('/revoke')) return response(204);
      return typeof reply === 'function' ? reply(init) : reply;
    }, onPaired: () => { starts++; }});
  await gate.ready;
  dom.nodes.get('[data-operator-pairing-code]').value = 'private-pairing-code';
  dom.nodes.get('[data-operator-pairing-form]').fire('submit');
  await tick(); await tick();
  return {dom, gate, requests, starts: () => starts,
    text: () => dom.nodes.get('[data-operator-pairing-status]').textContent};
}

test('validated checkpoint upgrade code displays fixed local migration guidance without server text', async () => {
  const run = await submitPairReply(upgradeResponse());
  assert.match(run.text(), /旧剧情存档/);
  assert.match(run.text(), /tools\/story_checkpoint\.py dry-run/);
  assert.match(run.text(), /--db.*--scope.*--authorize-story-checkpoint/);
  assert.match(run.text(), /不会自动升级/);
  assert.doesNotMatch(run.text(), /UNTRUSTED_SECRET|private\/database|private-pairing-code|synthetic-request/);
  assert.equal(run.starts(), 0);
  assert.equal(run.dom.nodes.get('[data-operator-pairing-code]').value, '');
  assert.equal(run.requests.length, 2);
});

for (const [label, makeReply] of [
  ['unknown code', () => upgradeResponse({code: 'different_upgrade'})],
  ['numeric code', () => upgradeResponse({code: 409})],
  ['wrong status', () => upgradeResponse({}, 503)],
  ['extra field', () => upgradeResponse({private_path: '/private/secret'})],
  ['non-string message', () => upgradeResponse({message: {secret: true}})],
  ['array body', () => new Response(JSON.stringify([{code: upgradeCode}]), {status: 409, headers: {'Content-Type': 'application/json'}})],
  ['invalid json', () => new Response('{broken', {status: 409, headers: {'Content-Type': 'application/json'}})],
  ['wrong content type', () => upgradeResponse({}, 409, {'Content-Type': 'text/html'})],
  ['oversized bytes', () => upgradeResponse({message: '秘密'.repeat(800)})],
  ['oversized declared length', () => upgradeResponse({}, 409, {'Content-Length': '9000'})],
]) {
  test(`checkpoint guidance rejects ${label} with generic safe failure`, async () => {
    const run = await submitPairReply(makeReply());
    assert.match(run.text(), /配对未完成/);
    assert.doesNotMatch(run.text(), /tools\/story_checkpoint|UNTRUSTED_SECRET|秘密|private\/secret/);
    assert.equal(run.starts(), 0);
  });
}

test('checkpoint body deadline settles even if response body never finishes; late bytes cannot revive guidance', async () => {
  const chunk = deferred();
  let reads = 0;
  const run = await submitPairReply({status: 409, headers: new Headers({'Content-Type': 'application/json'}),
    body: {getReader() {return {read() {reads++; return chunk.promise;}, async cancel() {}, releaseLock() {}};}}},
    {deadlineMs: 20});
  await new Promise(resolve => setTimeout(resolve, 45));
  assert.equal(reads, 1);
  assert.match(run.text(), /配对未完成/);
  const failed = run.text();
  chunk.resolve({done: false, value: new TextEncoder().encode(JSON.stringify({code: upgradeCode}))});
  await tick(); await tick();
  assert.equal(run.text(), failed);
  assert.equal(run.starts(), 0);
});

test('close during checkpoint error parsing fences the old generation and still revokes', async () => {
  const chunk = deferred();
  let entered = false;
  const run = await submitPairReply({status: 409, headers: new Headers({'Content-Type': 'application/json'}),
    body: {getReader() {return {read() {entered = true; return chunk.promise;}, async cancel() {}, releaseLock() {}};}}});
  assert.equal(entered, true, 'the known-error body is being parsed');
  await run.gate.close();
  const closed = run.text();
  assert.match(closed, /配对已撤销/);
  chunk.resolve({done: false, value: new TextEncoder().encode(JSON.stringify({code: upgradeCode}))});
  await tick(); await tick();
  assert.equal(run.text(), closed);
  assert.doesNotMatch(run.text(), /旧剧情存档/);
  assert.equal(run.starts(), 0);
  assert.equal(run.requests.filter(item => item.url.endsWith('/revoke')).length, 1);
});


test('private device refresh stops its local session but preserves bounded pairing; explicit close revokes', async () => {
  const dom = pairingDom();
  dom.document.body = {dataset: {deviceAccess: 'private'}};
  const calls=[];
  const gate = mountOperatorPairing(dom.document, {
    fetcher: async path => { calls.push(path); return path.endsWith('/status') ? statusResponse(true) : response(204); },
    onPaired: () => ({async stopAndClose() { calls.push('local-close'); }}),
  });
  await gate.ready;
  dom.window.fire('pagehide');await tick();
  assert.ok(calls.includes('local-close'));
  assert.ok(!calls.includes('/api/v1/operator/revoke'));
  await gate.cancelAndRevoke();
  assert.equal(calls.filter(value=>value==='/api/v1/operator/revoke').length,1);
});
