import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import vm from 'node:vm';

const markup = await readFile(new URL('../../apps/web/index.html', import.meta.url), 'utf8');
const css = await readFile(new URL('../../apps/web/public/app.css', import.meta.url), 'utf8');
const managementSource = await readFile(new URL('../../apps/web/src/features/session/memory-management.ts', import.meta.url), 'utf8');
const dist = process.env.MIRA_TEST_WEB_DIST ? resolve(process.env.MIRA_TEST_WEB_DIST) : resolve('apps/web/dist');
const {mountMemoryManagement} = await import(resolve(dist, 'features/session/memory-management.js'));
const mainSource = await readFile(resolve(dist, 'app/main-source.js'), 'utf8');

function deferred() {
  let resolvePromise;
  const promise = new Promise(resolve => { resolvePromise = resolve; });
  return {promise, resolve: resolvePromise};
}

class FakeElement {
  listeners = new Map();
  children = [];
  dataset = {};
  value = '';
  textContent = '';
  className = '';
  type = '';
  hidden = false;
  disabled = false;
  checked = false;
  open = false;
  constructor(tagName = 'div') { this.tagName = tagName.toUpperCase(); }
  addEventListener(name, listener) {
    const list = this.listeners.get(name) ?? [];
    list.push(listener);
    this.listeners.set(name, list);
  }
  fire(name, extras = {}) {
    const event = {defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extras};
    for (const listener of this.listeners.get(name) ?? []) listener(event);
    return event;
  }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = [...children]; }
  all(selector) {
    const isButton = selector === 'button' && this.tagName === 'BUTTON';
    const ownMatch = isButton || selector === '[data-memory-management-propose]'
      && this.dataset['memoryManagementPropose'] === 'true';
    return [...(ownMatch ? [this] : []), ...this.children.flatMap(child => child.all(selector))];
  }
  querySelectorAll(selector) { return this.all(selector); }
  querySelector(selector) {
    return this.all(selector)[0] ?? null;
  }
}

const ENTRY_ID = 'saved-tea';
const FORGET_ID = '0123456789abcdef0123456789abcdef';
const OPERATION_ID = '00000000-0000-4000-8000-000000000099';
const REQUEST_ID = 'a1b2c3d4-e5f6-4789-abcd-0123456789ab';
const pageCursor = (revision, sequence) => btoa(`${revision}:${sequence}`).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
const sampleEntry = (changes = {}) => ({
  entry_id: ENTRY_ID, text: 'Synthetic private note <img src=x onerror=alert(1)>', kind: 'episodic',
  source: 'user_statement', source_version: 1, recorded_at: '2026-10-04T15:00:00Z', active: true,
  forget_event_id: null, forgotten_at: null, ...changes,
});
const statusOk = (revision = 4) => ({enabled: true, revision});
const pageOk = (changes = {}) => ({revision: 4, entries: [sampleEntry()], next_cursor: null, ...changes});
function response(status, value, options = {}) {
  const body = options.bodyStream ?? JSON.stringify(value);
  const headers = {'content-type': 'application/json'};
  if (typeof options.requestId === 'string') headers['X-Request-ID'] = options.requestId;
  return new Response(body, {status, headers});
}
const committed = (operationId = OPERATION_ID, changes = {}) => response(200, {
  status: 'committed', operation_id: operationId, revision: 5, entry_id: ENTRY_ID, event_id: null, replayed: false, ...changes,
});
const tick = () => new Promise(resolve => setImmediate(resolve));
async function settle() { await tick(); await tick(); await tick(); }

function managementDom() {
  const selectors = {
    '[data-memory-management-panel]': new FakeElement('details'),
    '[data-memory-management-status]': new FakeElement('p'),
    '[data-memory-management-entries]': new FakeElement('ol'),
    '[data-memory-management-refresh]': new FakeElement('button'),
    '[data-memory-management-previous]': new FakeElement('button'),
    '[data-memory-management-next]': new FakeElement('button'),
    '[data-memory-management-local-consent]': new FakeElement('input'),
    'form[data-memory-management-record-form]': new FakeElement('form'),
    '[data-memory-management-text]': new FakeElement('textarea'),
    '[data-memory-management-kind]': new FakeElement('select'),
    '[data-memory-management-editor-title]': new FakeElement('h3'),
    '[data-memory-management-cancel-edit]': new FakeElement('button'),
    '[data-memory-management-confirmation]': new FakeElement('section'),
    '[data-memory-management-preview]': new FakeElement('p'),
    '[data-memory-management-confirmed]': new FakeElement('input'),
    '[data-memory-management-commit]': new FakeElement('button'),
    '[data-memory-management-cancel]': new FakeElement('button'),
    '[data-memory-management-reconcile]': new FakeElement('button'),
    '.memory-management-disclosure': new FakeElement('p'),
    '.memory-management-retention': new FakeElement('p'),
  };
  const propose = new FakeElement('button');
  propose.dataset['memoryManagementPropose'] = 'true';
  selectors['form[data-memory-management-record-form]'].appendChild(propose);
  selectors['form[data-memory-management-record-form]'].appendChild(selectors['[data-memory-management-cancel-edit]']);
  const document = {
    defaultView: new FakeElement('window'),
    querySelector: selector => selectors[selector] ?? null,
    createElement: tagName => new FakeElement(tagName),
  };
  return {document, nodes: selectors, propose};
}

function actionButton(list, action) {
  for (const row of list.children) {
    const match = row.all('button').find(button => button.dataset['memoryManagementAction'] === action);
    if (match) return match;
  }
  return null;
}

function entryPageFetcher({entryPage = pageOk(), statusValue = statusOk(), requests = [], onPost} = {}) {
  return {
    requests,
    fetcher(url, init) {
      requests.push({url, init});
      if (url === '/api/v1/memory-management/status') return Promise.resolve(response(200, statusValue));
      if (url.startsWith('/api/v1/memory-management/entries?')) return Promise.resolve(response(200, entryPage));
      if (url === '/api/v1/memory-management/operations') return onPost?.(url, init) ?? Promise.resolve(committed());
      throw new Error('unexpected fixed route');
    },
  };
}

test('paired management markup is a collapsed, explicit, locally scoped surface', () => {
  assert.match(markup, /<details class="memory-management-panel" data-memory-management-panel hidden/);
  assert.doesNotMatch(markup.match(/<details class="memory-management-panel"[^>]*>/)?.[0] ?? '', /\bopen(?:[\s=>])/);
  assert.match(markup, /data-memory-management-record-form/);
  assert.match(markup, /data-memory-management-local-consent/);
  assert.match(markup, /data-memory-management-confirm/);
  assert.match(markup, /data-memory-management-entries/);
  assert.match(markup, /data-memory-management-status/);
  assert.match(markup, /data-memory-management-reconcile/);
  assert.match(markup, /本机操作方显式启用/);
  assert.match(markup, /Codex/);
  assert.match(markup, /TypeSafe\/JEV/);
  assert.match(markup, /仍留在本机追加历史|这不是安全删除/);
  assert.match(css, /\.memory-management-panel/);
  assert.doesNotMatch(managementSource, /\b(?:localStorage|sessionStorage|clipboard|console|location)\b|\.innerHTML\s*=/);
  assert.match(managementSource, /body\.textContent = entry\.text/);
});

test('management, pairing, and chat forms retain exact selector semantics', () => {
  const forms = [...markup.matchAll(/<form\b[^>]*>/g)].map(match => match[0]);
  assert.ok(forms.length >= 3, 'pairing, local memory, and conversation forms are distinct');
  assert.match(forms[0], /data-operator-pairing-form/);
  assert.match(forms.find(form => form.includes('data-memory-management-record-form')) ?? '', /data-memory-management-record-form/);
  assert.match(forms.find(form => /class="composer"/.test(form)) ?? '', /class="composer"/);
  assert.doesNotMatch(markup, /querySelector\s*\(\s*['"]form['"]\s*\)/);
  assert.match(markup, /data-memory-management-panel[^>]*hidden/);
  assert.match(markup, /local-memory management is off by default|本机记忆管理默认关闭/);
});

test('the panel does not read before the collapsed disclosure is opened and uses bounded fixed GETs', async () => {
  const dom = managementDom();
  const fixture = entryPageFetcher();
  const app = mountMemoryManagement(dom.document, {fetcher: fixture.fetcher, deadlineMs: 100});
  assert.equal(dom.nodes['[data-memory-management-panel]'].hidden, false);
  assert.equal(fixture.requests.length, 0, 'mounting after pairing does not load text until the user opens the panel');
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  assert.deepEqual(fixture.requests.map(request => request.url), [
    '/api/v1/memory-management/status', '/api/v1/memory-management/entries?limit=20',
  ]);
  for (const {init} of fixture.requests) {
    assert.equal(init.credentials, 'include');
    assert.equal(init.cache, 'no-store');
    assert.equal(init.redirect, 'error');
  }
  assert.equal(dom.nodes['[data-memory-management-entries]'].children.length, 1);
  assert.equal(dom.nodes['[data-memory-management-entries]'].children[0].children[0].textContent, sampleEntry().text);
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /第 1 页/);
  app.close();
});

test('legacy CLI text uses stored-entry limits distinct from the stricter editor limit', async () => {
  const dom = managementDom();
  const asciiText = 'x'.repeat(5_000);
  const astralText = '🌧'.repeat(3_000);
  const fixture = entryPageFetcher({entryPage: pageOk({entries: [
    sampleEntry({entry_id: 'legacy-ascii', text: asciiText}),
    sampleEntry({entry_id: 'legacy-astral', text: astralText}),
  ]})});
  const app = mountMemoryManagement(dom.document, {fetcher: fixture.fetcher});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  assert.equal(dom.nodes['[data-memory-management-entries]'].children[0].children[0].textContent, asciiText);
  assert.equal(dom.nodes['[data-memory-management-entries]'].children[1].children[0].textContent, astralText);
  app.close();

  const oversized = managementDom();
  const oversizedFetcher = entryPageFetcher({entryPage: pageOk({entries: [sampleEntry({
    entry_id: 'too-many-codepoints', text: '🌧'.repeat(16_385),
  })]})});
  const oversizedApp = mountMemoryManagement(oversized.document, {fetcher: oversizedFetcher.fetcher});
  oversized.nodes['[data-memory-management-panel]'].open = true;
  oversized.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  assert.match(oversized.nodes['[data-memory-management-status]'].textContent, /回复格式无效/);
  assert.equal(oversized.nodes['[data-memory-management-entries]'].children.length, 0);
  oversizedApp.close();
});

test('memory page text budget rejects a page whose rows exceed 128 KiB total', async () => {
  const dom = managementDom();
  const entries = Array.from({length: 4}, (_unused, index) => sampleEntry({
    entry_id: `large-row-${index}`, text: '🌧'.repeat(9_000),
  }));
  const fixture = entryPageFetcher({entryPage: pageOk({entries})});
  const app = mountMemoryManagement(dom.document, {fetcher: fixture.fetcher});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /回复格式无效/);
  assert.equal(dom.nodes['[data-memory-management-entries]'].children.length, 0);
  app.close();
});

test('disabled server declaration shows the default-off explanation and never reads entries', async () => {
  const dom = managementDom();
  const fixture = entryPageFetcher({statusValue: {enabled: false, revision: null}});
  const app = mountMemoryManagement(dom.document, {fetcher: fixture.fetcher});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  assert.deepEqual(fixture.requests.map(request => request.url), ['/api/v1/memory-management/status']);
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /默认关闭/);
  assert.equal(dom.nodes['[data-memory-management-entries]'].children.length, 0);
  app.close();
});

test('authentication loss after a loaded page clears private entries and drafts', async () => {
  const dom = managementDom();
  let revoked = false;
  const requests = [];
  const fetcher = (url, init) => {
    requests.push({url, init});
    if (url === '/api/v1/memory-management/status') return Promise.resolve(revoked
      ? response(401, {secret: 'PRIVATE_ERROR'}, {requestId: REQUEST_ID}) : response(200, statusOk()));
    if (url.startsWith('/api/v1/memory-management/entries?')) return Promise.resolve(response(200, pageOk()));
    throw new Error('unexpected route');
  };
  const app = mountMemoryManagement(dom.document, {fetcher});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  assert.equal(dom.nodes['[data-memory-management-entries]'].children.length, 1);
  dom.nodes['[data-memory-management-local-consent]'].checked = true;
  dom.nodes['[data-memory-management-local-consent]'].fire('change');
  dom.nodes['[data-memory-management-text]'].value = 'Synthetic private draft';
  dom.nodes['form[data-memory-management-record-form]'].fire('submit');
  assert.equal(dom.nodes['[data-memory-management-confirmation]'].hidden, false);
  revoked = true;
  dom.nodes['[data-memory-management-refresh]'].fire('click');
  await settle();
  assert.equal(dom.nodes['[data-memory-management-entries]'].children.length, 0);
  assert.equal(dom.nodes['[data-memory-management-text]'].value, '');
  assert.equal(dom.nodes['[data-memory-management-local-consent]'].checked, false);
  assert.equal(dom.nodes['[data-memory-management-confirmation]'].hidden, true);
  assert.equal(dom.nodes['[data-memory-management-reconcile]'].hidden, true);
  const status = dom.nodes['[data-memory-management-status]'].textContent;
  assert.match(status, /配对已失效/);
  assert.doesNotMatch(status, /PRIVATE_ERROR|Synthetic private draft/);
  app.close();
});

test('bounded pages use only the opaque cursor, support previous, and disclose the twenty-page cap', async () => {
  const dom = managementDom();
  const requests = [];
  let pageNumber = 1;
  const fetcher = (url, init) => {
    requests.push({url, init});
    if (url === '/api/v1/memory-management/status') return Promise.resolve(response(200, statusOk()));
    if (url.startsWith('/api/v1/memory-management/entries?')) {
      if (url.includes(`cursor=${pageCursor(4, 2)}`)) pageNumber = 2;
      else pageNumber = 1;
      return Promise.resolve(response(200, pageOk({entries: [sampleEntry({entry_id: `page-${pageNumber}`, text: `Synthetic page ${pageNumber}`})],
        next_cursor: pageNumber === 1 ? pageCursor(4, 2) : null})));
    }
    throw new Error('unexpected route');
  };
  const app = mountMemoryManagement(dom.document, {fetcher});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  dom.nodes['[data-memory-management-next]'].fire('click');
  await settle();
  assert.ok(requests.some(({url}) => url === `/api/v1/memory-management/entries?limit=20&cursor=${pageCursor(4, 2)}`));
  assert.equal(dom.nodes['[data-memory-management-entries]'].children[0].children[0].textContent, 'Synthetic page 2');
  assert.equal(dom.nodes['[data-memory-management-previous]'].disabled, false);
  dom.nodes['[data-memory-management-previous]'].fire('click');
  await settle();
  assert.equal(dom.nodes['[data-memory-management-entries]'].children[0].children[0].textContent, 'Synthetic page 1');
  assert.ok(requests.every(({url}) => !url.includes('Synthetic page')));
  app.close();

  const capped = managementDom();
  const cappedFetch = (url) => {
    if (url === '/api/v1/memory-management/status') return Promise.resolve(response(200, statusOk()));
    const query = new URLSearchParams(url.split('?')[1]);
    const cursor = query.get('cursor');
    pageNumber = cursor ? Number(atob(cursor.replace(/-/g, '+').replace(/_/g, '/')).split(':')[1]) : 1;
    return Promise.resolve(response(200, pageOk({entries: [], next_cursor: pageNumber < 21 ? pageCursor(4, pageNumber + 1) : null})));
  };
  const cappedApp = mountMemoryManagement(capped.document, {fetcher: cappedFetch});
  capped.nodes['[data-memory-management-panel]'].open = true;
  capped.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  for (let index = 0; index < 19; index++) {
    capped.nodes['[data-memory-management-next]'].fire('click');
    await settle();
  }
  assert.match(capped.nodes['[data-memory-management-status]'].textContent, /最多 20 页.*仍有后续页未显示/);
  assert.equal(capped.nodes['[data-memory-management-next]'].disabled, true);
  cappedApp.close();
});

test('opaque cursors must canonically encode only the displayed revision and sequence', async () => {
  const dom = managementDom();
  const fixture = entryPageFetcher({entryPage: pageOk({next_cursor: btoa('saved-tea').replace(/=+$/g, '')})});
  const app = mountMemoryManagement(dom.document, {fetcher: fixture.fetcher});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /回复格式无效/);
  assert.equal(dom.nodes['[data-memory-management-next]'].disabled, true);
  assert.ok(fixture.requests.every(({url}) => !url.includes('saved-tea')));
  app.close();
});

test('record requires separate local consent, readable confirmation, and a single confirmed operation', async () => {
  const dom = managementDom();
  const bodies = [];
  let revision = 4;
  const requests = [];
  const fetcher = (url, init) => {
    requests.push({url, init});
    if (url === '/api/v1/memory-management/status') return Promise.resolve(response(200, statusOk(revision)));
    if (url.startsWith('/api/v1/memory-management/entries?')) return Promise.resolve(response(200, pageOk({revision, entries: []})));
    if (url === '/api/v1/memory-management/operations') {
      bodies.push(init.body);
      revision++;
      return Promise.resolve(committed(JSON.parse(init.body).operation_id, {revision}));
    }
    throw new Error('unexpected fixed route');
  };
  const app = mountMemoryManagement(dom.document, {fetcher, newOperationId: () => OPERATION_ID});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  const draft = 'Synthetic record: keep the exact words';
  dom.nodes['[data-memory-management-text]'].value = draft;
  dom.nodes['form[data-memory-management-record-form]'].fire('submit');
  assert.equal(dom.nodes['[data-memory-management-confirmation]'].hidden, true);
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /本机写入同意/);
  dom.nodes['[data-memory-management-local-consent]'].checked = true;
  dom.nodes['[data-memory-management-local-consent]'].fire('change');
  dom.nodes['form[data-memory-management-record-form]'].fire('submit');
  assert.equal(dom.nodes['[data-memory-management-confirmation]'].hidden, false);
  assert.equal(dom.nodes['[data-memory-management-preview]'].textContent.includes(draft), true);
  assert.equal(bodies.length, 0, 'preparing a confirmation is not a write');
  dom.nodes['[data-memory-management-confirmed]'].checked = true;
  dom.nodes['[data-memory-management-confirmed]'].fire('change');
  dom.nodes['[data-memory-management-commit]'].fire('click');
  dom.nodes['[data-memory-management-commit]'].fire('click');
  await settle();
  assert.equal(bodies.length, 1, 'duplicate confirmation clicks are fenced');
  assert.deepEqual(JSON.parse(bodies[0]), {
    operation_id: OPERATION_ID, expected_revision: 4, operation: 'record', text: draft,
    kind: 'episodic', confirmed: true,
  });
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /已确认这项操作已提交/);
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /版本 5/);
  app.close();
});

test('write editor keeps its distinct 4096-codepoint and 16KiB UTF-8 bound', async () => {
  const dom = managementDom();
  const fixture = entryPageFetcher({entryPage: pageOk({entries: []})});
  const app = mountMemoryManagement(dom.document, {fetcher: fixture.fetcher});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  dom.nodes['[data-memory-management-local-consent]'].checked = true;
  dom.nodes['[data-memory-management-local-consent]'].fire('change');
  dom.nodes['[data-memory-management-text]'].value = 'x'.repeat(4_097);
  dom.nodes['form[data-memory-management-record-form]'].fire('submit');
  assert.equal(dom.nodes['[data-memory-management-confirmation]'].hidden, true);
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /4096 个 Unicode 字符/);
  assert.equal(fixture.requests.filter(request => request.url === '/api/v1/memory-management/operations').length, 0);
  app.close();
});

test('correct, soft-forget, and restore send only their contracted target fields', async () => {
  const dom = managementDom();
  const bodies = [];
  let currentRevision = 4;
  let currentEntry = sampleEntry();
  let nextId = 91;
  const requests = [];
  const fetcher = (url, init) => {
    requests.push({url, init});
    if (url === '/api/v1/memory-management/status') return Promise.resolve(response(200, statusOk(currentRevision)));
    if (url.startsWith('/api/v1/memory-management/entries?')) {
      return Promise.resolve(response(200, pageOk({revision: currentRevision, entries: [currentEntry]})));
    }
    if (url === '/api/v1/memory-management/operations') {
      const body = JSON.parse(init.body);
      bodies.push(body);
      currentRevision++;
      if (body.operation === 'correct') currentEntry = sampleEntry({text: body.text, source_version: 2});
      if (body.operation === 'forget') currentEntry = sampleEntry({active: false, forget_event_id: FORGET_ID, forgotten_at: '2026-10-04T15:04:00Z'});
      if (body.operation === 'restore') currentEntry = sampleEntry();
      return Promise.resolve(committed(body.operation_id, {revision: currentRevision,
        event_id: body.operation === 'forget' || body.operation === 'restore' ? FORGET_ID : null}));
    }
    throw new Error('unexpected fixed route');
  };
  const app = mountMemoryManagement(dom.document, {fetcher,
    newOperationId: () => `00000000-0000-4000-8000-${String(nextId++).padStart(12, '0')}`});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  dom.nodes['[data-memory-management-local-consent]'].checked = true;
  dom.nodes['[data-memory-management-local-consent]'].fire('change');

  actionButton(dom.nodes['[data-memory-management-entries]'], 'correct').fire('click');
  dom.nodes['[data-memory-management-text]'].value = 'Synthetic corrected wording';
  dom.nodes['form[data-memory-management-record-form]'].fire('submit');
  dom.nodes['[data-memory-management-confirmed]'].checked = true;
  dom.nodes['[data-memory-management-confirmed]'].fire('change');
  dom.nodes['[data-memory-management-commit]'].fire('click');
  await settle();

  actionButton(dom.nodes['[data-memory-management-entries]'], 'forget').fire('click');
  dom.nodes['[data-memory-management-confirmed]'].checked = true;
  dom.nodes['[data-memory-management-confirmed]'].fire('change');
  dom.nodes['[data-memory-management-commit]'].fire('click');
  await settle();

  actionButton(dom.nodes['[data-memory-management-entries]'], 'restore').fire('click');
  assert.match(dom.nodes['[data-memory-management-preview]'].textContent, /恢复这条陈述对应的一项软忘记事件/);
  dom.nodes['[data-memory-management-confirmed]'].checked = true;
  dom.nodes['[data-memory-management-confirmed]'].fire('change');
  dom.nodes['[data-memory-management-commit]'].fire('click');
  await settle();

  assert.deepEqual(bodies.map(({operation, ...body}) => [operation, body]), [
    ['correct', {operation_id: '00000000-0000-4000-8000-000000000091', expected_revision: 4,
      entry_id: ENTRY_ID, text: 'Synthetic corrected wording', confirmed: true}],
    ['forget', {operation_id: '00000000-0000-4000-8000-000000000092', expected_revision: 5,
      entry_id: ENTRY_ID, confirmed: true}],
    ['restore', {operation_id: '00000000-0000-4000-8000-000000000093', expected_revision: 6,
      forget_event_id: FORGET_ID, confirmed: true}],
  ]);
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /已确认这项操作已提交/);
  app.close();
});

test('Stop clears an unsubmitted confirmation and does not claim a sent operation was undone', async () => {
  const dom = managementDom();
  const post = deferred();
  let posts = 0;
  let postSignal;
  let revision = 4;
  const requests = [];
  const fetcher = (url, init) => {
    requests.push({url, init});
    if (url === '/api/v1/memory-management/status') return Promise.resolve(response(200, statusOk(revision)));
    if (url.startsWith('/api/v1/memory-management/entries?')) return Promise.resolve(response(200, pageOk({revision, entries: []})));
    if (url === '/api/v1/memory-management/operations') { posts++; postSignal = init.signal; return post.promise; }
    throw new Error('unexpected fixed route');
  };
  const app = mountMemoryManagement(dom.document, {fetcher, newOperationId: () => OPERATION_ID});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  dom.nodes['[data-memory-management-local-consent]'].checked = true;
  dom.nodes['[data-memory-management-local-consent]'].fire('change');
  dom.nodes['[data-memory-management-text]'].value = 'Synthetic draft to clear';
  dom.nodes['form[data-memory-management-record-form]'].fire('submit');
  dom.nodes['[data-memory-management-confirmed]'].checked = true;
  dom.nodes['[data-memory-management-confirmed]'].fire('change');
  app.stop();
  assert.equal(dom.nodes['[data-memory-management-confirmation]'].hidden, true);
  assert.equal(dom.nodes['[data-memory-management-text]'].value, '');
  assert.equal(posts, 0);

  dom.nodes['[data-memory-management-text]'].value = 'Synthetic committed request';
  dom.nodes['form[data-memory-management-record-form]'].fire('submit');
  dom.nodes['[data-memory-management-confirmed]'].checked = true;
  dom.nodes['[data-memory-management-confirmed]'].fire('change');
  dom.nodes['[data-memory-management-commit]'].fire('click');
  app.stop();
  assert.equal(posts, 1);
  assert.equal(postSignal.aborted, false, 'Stop cancels unsubmitted confirmation but keeps a sent write honest');
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /停止回应不会撤销/);
  revision++;
  post.resolve(committed(OPERATION_ID, {revision}));
  await settle();
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /已确认这项操作已提交/);
  app.close();
});

test('uncertain write is never automatic and reconciliation repeats the byte-identical operation', async () => {
  const dom = managementDom();
  const bodies = [];
  let calls = 0;
  let revision = 4;
  const requests = [];
  const fetcher = (url, init) => {
    requests.push({url, init});
    if (url === '/api/v1/memory-management/status') return Promise.resolve(response(200, statusOk(revision)));
    if (url.startsWith('/api/v1/memory-management/entries?')) return Promise.resolve(response(200, pageOk({revision, entries: []})));
    if (url === '/api/v1/memory-management/operations') {
      bodies.push(init.body);
      calls++;
      if (calls === 1) return Promise.reject(new Error('synthetic transport secret'));
      revision++;
      return Promise.resolve(committed(OPERATION_ID, {revision, replayed: true}));
    }
    throw new Error('unexpected fixed route');
  };
  const app = mountMemoryManagement(dom.document, {fetcher, newOperationId: () => OPERATION_ID});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  dom.nodes['[data-memory-management-local-consent]'].checked = true;
  dom.nodes['[data-memory-management-local-consent]'].fire('change');
  dom.nodes['[data-memory-management-text]'].value = 'Synthetic uncertain record';
  dom.nodes['form[data-memory-management-record-form]'].fire('submit');
  dom.nodes['[data-memory-management-confirmed]'].checked = true;
  dom.nodes['[data-memory-management-confirmed]'].fire('change');
  dom.nodes['[data-memory-management-commit]'].fire('click');
  await settle();
  assert.equal(calls, 1);
  assert.equal(dom.nodes['[data-memory-management-reconcile]'].hidden, false);
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /不确定/);
  assert.doesNotMatch(dom.nodes['[data-memory-management-status]'].textContent, /synthetic transport secret/);
  dom.nodes['[data-memory-management-local-consent]'].checked = false;
  dom.nodes['[data-memory-management-local-consent]'].fire('change');
  assert.equal(dom.nodes['[data-memory-management-reconcile]'].disabled, true);
  dom.nodes['[data-memory-management-reconcile]'].fire('click');
  await settle();
  assert.equal(calls, 1, 'reconciliation cannot resend after local write consent is withdrawn');
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /不会再发送核对请求/);
  dom.nodes['[data-memory-management-local-consent]'].checked = true;
  dom.nodes['[data-memory-management-local-consent]'].fire('change');
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /若原请求尚未提交，这会执行原操作/);
  dom.nodes['[data-memory-management-reconcile]'].fire('click');
  dom.nodes['[data-memory-management-reconcile]'].fire('click');
  await settle();
  assert.equal(calls, 2);
  assert.equal(bodies[0], bodies[1]);
  assert.equal(JSON.parse(bodies[1]).operation_id, OPERATION_ID);
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /先前成功提交，没有重复添加/);
  app.close();
});

test('conflict and raw error text are reduced to fixed safe UI messages', async () => {
  const dom = managementDom();
  const fixture = entryPageFetcher({entryPage: pageOk({entries: []}), onPost: () => Promise.resolve(response(409, {
    code: 'stale_revision', message: 'SECRET_FROM_ERROR_BODY', request_id: 'synthetic-request', current_revision: 5,
  }, {requestId: REQUEST_ID}))});
  const app = mountMemoryManagement(dom.document, {fetcher: fixture.fetcher, newOperationId: () => OPERATION_ID});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  dom.nodes['[data-memory-management-local-consent]'].checked = true;
  dom.nodes['[data-memory-management-local-consent]'].fire('change');
  dom.nodes['[data-memory-management-text]'].value = 'Synthetic conflict payload';
  dom.nodes['form[data-memory-management-record-form]'].fire('submit');
  dom.nodes['[data-memory-management-confirmed]'].checked = true;
  dom.nodes['[data-memory-management-confirmed]'].fire('change');
  dom.nodes['[data-memory-management-commit]'].fire('click');
  await settle();
  const status = dom.nodes['[data-memory-management-status]'].textContent;
  assert.match(status, /版本已变化/);
  assert.doesNotMatch(status, /SECRET_FROM_ERROR_BODY|synthetic-request|Synthetic conflict payload/);
  assert.match(status, new RegExp(`诊断编号：${REQUEST_ID}`));
  assert.equal(dom.nodes['[data-memory-management-reconcile]'].hidden, true);
  assert.equal(dom.nodes['[data-memory-management-refresh]'].disabled, false);
  assert.equal(fixture.requests.filter(request => request.url === '/api/v1/memory-management/operations').length, 1);
  app.close();
});

test('response bodies remain bounded after headers and invalid X-Request-ID values never surface', async () => {
  for (const requestId of ['sk-live-secret-value-12345678901234567890', 'x'.repeat(4096)]) {
    const dom = managementDom();
    const fixture = entryPageFetcher({requests: [], onPost: undefined,
      statusValue: statusOk()});
    const fetcher = (url, init) => {
      fixture.requests.push({url, init});
      if (url === '/api/v1/memory-management/status') return Promise.resolve(response(500, {secret: 'SECRET_BODY'}, {requestId}));
      throw new Error('status failure must stop before entries GET');
    };
    const app = mountMemoryManagement(dom.document, {fetcher});
    dom.nodes['[data-memory-management-panel]'].open = true;
    dom.nodes['[data-memory-management-panel]'].fire('toggle');
    await settle();
    const status = dom.nodes['[data-memory-management-status]'].textContent;
    assert.doesNotMatch(status, /sk-live-secret|SECRET_BODY|x{20}/);
    assert.doesNotMatch(status, /诊断编号：/);
    app.close();
  }

  let bodyCancelled = false;
  const pendingBody = new ReadableStream({cancel() { bodyCancelled = true; }});
  const hanging = managementDom();
  const hangingFetcher = url => url === '/api/v1/memory-management/status'
    ? Promise.resolve(new Response(pendingBody, {status: 200, headers: {'content-type': 'application/json'}}))
    : Promise.reject(new Error('entries request must not run before bounded status JSON'));
  const hangingApp = mountMemoryManagement(hanging.document, {fetcher: hangingFetcher, deadlineMs: 20});
  hanging.nodes['[data-memory-management-panel]'].open = true;
  hanging.nodes['[data-memory-management-panel]'].fire('toggle');
  await new Promise(resolve => setTimeout(resolve, 60));
  await settle();
  assert.match(hanging.nodes['[data-memory-management-status]'].textContent, /读取结果未确认/);
  assert.equal(bodyCancelled, true);
  hangingApp.close();

  let oversizedCancelled = false;
  const hugeStream = new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(512 * 1024 + 1)); controller.close(); },
    cancel() { oversizedCancelled = true; },
  });
  const oversized = managementDom();
  const oversizedFetcher = url => url === '/api/v1/memory-management/status'
    ? Promise.resolve(new Response(hugeStream, {status: 200, headers: {'content-type': 'application/json'}}))
    : Promise.reject(new Error('entries request must not run before bounded status JSON'));
  const oversizedApp = mountMemoryManagement(oversized.document, {fetcher: oversizedFetcher});
  oversized.nodes['[data-memory-management-panel]'].open = true;
  oversized.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  assert.match(oversized.nodes['[data-memory-management-status]'].textContent, /读取结果未确认/);
  assert.equal(oversized.nodes['[data-memory-management-entries]'].children.length, 0);
  oversizedApp.close();
});

test('late reads and writes are aborted and fenced on close, with private text cleared', async () => {
  const dom = managementDom();
  const pending = deferred();
  let entrySignal;
  const requests = [];
  const fetcher = (url, init) => {
    requests.push({url, init});
    if (url === '/api/v1/memory-management/status') return Promise.resolve(response(200, statusOk()));
    if (url.startsWith('/api/v1/memory-management/entries?')) { entrySignal = init.signal; return pending.promise; }
    throw new Error('unexpected route');
  };
  const app = mountMemoryManagement(dom.document, {fetcher});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  app.close();
  assert.equal(entrySignal.aborted, true);
  pending.resolve(response(200, pageOk({entries: [sampleEntry({text: 'Synthetic late secret'})]})));
  await settle();
  assert.equal(dom.nodes['[data-memory-management-entries]'].children.length, 0);
  assert.equal(dom.nodes['[data-memory-management-panel]'].hidden, true);
  assert.equal(dom.nodes['[data-memory-management-text]'].value, '');
  assert.doesNotMatch(dom.nodes['[data-memory-management-status]'].textContent, /Synthetic late secret/);

  const writeDom = managementDom();
  const lateWrite = deferred();
  let writeSignal;
  const writeFetcher = (url, init) => {
    if (url === '/api/v1/memory-management/status') return Promise.resolve(response(200, statusOk()));
    if (url.startsWith('/api/v1/memory-management/entries?')) return Promise.resolve(response(200, pageOk({entries: []})));
    if (url === '/api/v1/memory-management/operations') { writeSignal = init.signal; return lateWrite.promise; }
    throw new Error('unexpected route');
  };
  const writeApp = mountMemoryManagement(writeDom.document, {fetcher: writeFetcher, newOperationId: () => OPERATION_ID});
  writeDom.nodes['[data-memory-management-panel]'].open = true;
  writeDom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  writeDom.nodes['[data-memory-management-local-consent]'].checked = true;
  writeDom.nodes['[data-memory-management-local-consent]'].fire('change');
  writeDom.nodes['[data-memory-management-text]'].value = 'Synthetic write closed in flight';
  writeDom.nodes['form[data-memory-management-record-form]'].fire('submit');
  writeDom.nodes['[data-memory-management-confirmed]'].checked = true;
  writeDom.nodes['[data-memory-management-confirmed]'].fire('change');
  writeDom.nodes['[data-memory-management-commit]'].fire('click');
  await settle();
  assert.equal(writeSignal.aborted, false);
  writeApp.close();
  assert.equal(writeSignal.aborted, true);
  assert.equal(writeDom.nodes['[data-memory-management-entries]'].children.length, 0);
  assert.equal(writeDom.nodes['[data-memory-management-text]'].value, '');
  assert.equal(writeDom.nodes['[data-memory-management-local-consent]'].checked, false);
  const closedStatus = writeDom.nodes['[data-memory-management-status]'].textContent;
  lateWrite.resolve(committed());
  await settle();
  assert.equal(writeDom.nodes['[data-memory-management-status]'].textContent, closedStatus);
  assert.doesNotMatch(closedStatus, /Synthetic write closed in flight|已确认这项操作已提交/);
});

test('main mounts only after pairing and only for the exact server management marker', async () => {
  const calls = [];
  const nodes = new Map();
  const pairingForm = new FakeElement('form');
  class Node extends FakeElement {
    setAttribute(name, value) { this[name] = value; }
    setPointerCapture() {}
  }
  const doc = {
    body: {dataset: {operatorPairing: 'required', memoryManagement: 'enabled'}},
    visibilityState: 'visible',
    querySelector(selector) { if (selector === 'form') return pairingForm; if (!nodes.has(selector)) nodes.set(selector, new Node()); return nodes.get(selector); },
    querySelectorAll() { return []; }, addEventListener() {},
  };
  const window = new Node();
  let pairingOptions;
  let pairedApp;
  class Controller {
    microphoneBusy = false;
    constructor() { calls.push('controller'); }
    connect() { calls.push('connect'); return Promise.resolve(); }
    stop() { calls.push('controller-stop'); return Promise.resolve(); }
    close() { calls.push('controller-close'); return Promise.resolve(); }
    setContinuousListeningPhase() {}
  }
  class ReviewPanel {
    recordingActive = false;
    setCanEnable() {} setContinuousListeningBlocked() {} start() {} close() {} invalidateForNewInput() {} invalidateForStop() {} auditionState() {}
  }
  class ContinuousListeningController {active=false;constructor(options){this.options=options;options.onUpdate({state:'idle',lease_id:null,ready:null,transcript:null,sent_text:[],notice:null,error:null});}start(){this.active=true;return true;}stop(){this.active=false;return Promise.resolve();}close(){this.active=false;return Promise.resolve();}sendCurrent(){return Promise.resolve();}}
  const source = mainSource.replace(/^import .*;\n/gm, '');
  vm.runInNewContext(source, {
    document: doc, window,
    globalThis: {AudioContext: class {}, AudioWorkletNode: class {}, isSecureContext: true},
    navigator: {mediaDevices: {getUserMedia() {}}},
    loadPublicConfig: () => ({}),
    watchDiagnosticsStatus() { calls.push('watch'); return {close() {}}; },
    recordingNotice: () => ({visible: false, text: '', state: 'off'}), safeSessionError: () => 'safe error',
    mountOperatorPairing(_document, options) {
      calls.push('gate'); pairingOptions = options;
      return {cancelAndRevoke: async () => { calls.push('revoke-start'); await pairedApp?.stopAndClose(); calls.push('revoke-done'); }};
    },
    mountMemoryManagement() {
      calls.push('memory-panel');
      return {stop() { calls.push('memory-stop'); }, close() { calls.push('memory-close'); }};
    },
    MiraApiClient: class { constructor() { calls.push('api'); } },
    SessionController: Controller, ReviewedAudioPanel: ReviewPanel, ContinuousListeningController, SceneEffectExecutor: class {},
  });
  assert.deepEqual(calls, ['gate']);
  pairedApp = pairingOptions.onPaired();
  await settle();
  assert.deepEqual(calls.slice(0, 5), ['gate', 'memory-panel', 'watch', 'api', 'controller']);
  assert.equal(nodes.get('form.composer').listeners.get('submit').length, 1);
  assert.equal(pairingForm.listeners.has('submit'), false, 'the operator form is never mistaken for the chat composer');
  nodes.get('[data-stop]').fire('click');
  assert.ok(calls.indexOf('memory-stop') >= 0);
  assert.ok(calls.indexOf('controller-stop') < calls.indexOf('memory-stop'));
  nodes.get('[data-close]').fire('click');
  await settle();
  assert.ok(calls.indexOf('memory-close') < calls.indexOf('controller-stop', calls.lastIndexOf('memory-close')));
  assert.ok(calls.includes('revoke-done'));
});

test('page without both exact opt-in markers never mounts the management module', async () => {
  for (const dataset of [
    {operatorPairing: 'required'}, {memoryManagement: 'enabled'},
    {operatorPairing: 'required', memoryManagement: 'true'}, {},
  ]) {
    const calls = [];
    const nodes = new Map();
    class Node extends FakeElement { setAttribute(name, value) { this[name] = value; } setPointerCapture() {} }
    const doc = {body: {dataset}, visibilityState: 'visible',
      querySelector(selector) { if (!nodes.has(selector)) nodes.set(selector, new Node()); return nodes.get(selector); },
      querySelectorAll() { return []; }, addEventListener() {}};
    const source = mainSource.replace(/^import .*;\n/gm, '');
    vm.runInNewContext(source, {
      document: doc, window: new Node(), globalThis: {}, navigator: {},
      loadPublicConfig: () => ({}),
      watchDiagnosticsStatus() { return {close() {}}; }, recordingNotice: () => ({visible: false, text: '', state: 'off'}),
      safeSessionError: () => 'safe', mountOperatorPairing(_d, options) { calls.push('gate'); options.onPaired = () => undefined; return {cancelAndRevoke() {}}; },
      mountMemoryManagement() { calls.push('management'); return {stop() {}, close() {}}; },
      MiraApiClient: class {}, SessionController: class { microphoneBusy=false; connect() { return Promise.resolve(); } stop() { return Promise.resolve(); } close() { return Promise.resolve(); } setContinuousListeningPhase() {} },
      ReviewedAudioPanel: class {recordingActive=false; setCanEnable() {} setContinuousListeningBlocked() {} start() {} close() {} invalidateForNewInput() {} invalidateForStop() {} auditionState() {} },
      ContinuousListeningController: class {active=false;constructor(options){this.options=options;options.onUpdate({state:'idle',lease_id:null,ready:null,transcript:null,sent_text:[],notice:null,error:null});}start(){return true;}stop(){return Promise.resolve();}close(){return Promise.resolve();}sendCurrent(){return Promise.resolve();}},
      SceneEffectExecutor: class {},
    });
    await settle();
    assert.equal(calls.includes('management'), false, JSON.stringify(dataset));
  }
});

test('a committed edit from a later page refreshes from the new revision first page', async () => {
  const dom = managementDom();
  const requests = [];
  let revision = 4;
  const oldCursor = pageCursor(4, 2);
  const fetcher = async (url, init) => {
    requests.push({url, init});
    if (url.endsWith('/status')) return response(200, statusOk(revision));
    if (url.endsWith('/operations')) { revision = 5; return committed(); }
    if (url.includes('/entries?')) {
      if (revision === 5 && url.includes('cursor=')) return response(409, {code: 'stale_revision'});
      return response(200, pageOk({revision, next_cursor: revision === 4 && !url.includes('cursor=') ? oldCursor : null}));
    }
    throw new Error('unexpected route');
  };
  const app = mountMemoryManagement(dom.document, {fetcher, newOperationId: () => OPERATION_ID});
  dom.nodes['[data-memory-management-panel]'].open = true;
  dom.nodes['[data-memory-management-panel]'].fire('toggle');
  await settle();
  dom.nodes['[data-memory-management-next]'].fire('click');
  await settle();
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /第 2 页/);
  dom.nodes['[data-memory-management-local-consent]'].checked = true;
  dom.nodes['[data-memory-management-local-consent]'].fire('change');
  dom.nodes['[data-memory-management-text]'].value = 'Synthetic new note';
  dom.nodes['[data-memory-management-kind]'].value = 'episodic';
  dom.nodes['form[data-memory-management-record-form]'].fire('submit');
  dom.nodes['[data-memory-management-confirmed]'].checked = true;
  dom.nodes['[data-memory-management-confirmed]'].fire('change');
  dom.nodes['[data-memory-management-commit]'].fire('click');
  await settle();
  assert.equal(requests.filter(item => item.url.includes('/entries?')).at(-1).url,
    '/api/v1/memory-management/entries?limit=20');
  assert.match(dom.nodes['[data-memory-management-status]'].textContent, /第 1 页.*版本 5/);
  assert.doesNotMatch(dom.nodes['[data-memory-management-status]'].textContent, /刷新页未能匹配/);
  app.close();
});

test('standalone local-only disclosure never implies inherited provider permission', () => {
  const dom = managementDom();
  const app = mountMemoryManagement(dom.document, {localOnly: true, fetcher: async () => {
    throw new Error('no network expected before opening the panel');
  }});
  assert.match(dom.nodes['.memory-management-disclosure'].textContent, /不会向外部服务传送记忆内容/);
  assert.doesNotMatch(dom.nodes['.memory-management-disclosure'].textContent, /Codex|JEV|TypeSafe/);
  assert.match(dom.nodes['.memory-management-retention'].textContent, /不是安全删除/);
  assert.match(dom.nodes['.memory-management-retention'].textContent, /独立工具/);
  app.close();
});
