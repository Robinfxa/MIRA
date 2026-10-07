import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, readdir, rm, symlink, writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {parseBuildArgs, prepareBuildOutput, BUILD_OUTPUT_MARKER} from '../../tools/build_web.mjs';

async function fixture(t) {
  const parent = await mkdtemp(path.join(os.tmpdir(), 'mira-build-safety-'));
  const root = path.join(parent, 'project');
  await mkdir(path.join(root, 'apps/web/src'), {recursive: true});
  await mkdir(path.join(root, 'apps/web/public'), {recursive: true});
  await mkdir(path.join(root, 'tools'), {recursive: true});
  t.after(() => rm(parent, {recursive: true, force: true}));
  return {parent, root};
}

async function snapshot(directory) {
  const entries = [];
  async function visit(current, relative = '') {
    let children;
    try { children = await readdir(current, {withFileTypes: true}); }
    catch (error) { if (error.code === 'ENOENT') return; throw error; }
    for (const child of children.sort((a, b) => a.name.localeCompare(b.name))) {
      const name = path.posix.join(relative, child.name);
      const full = path.join(current, child.name);
      if (child.isSymbolicLink()) entries.push([name, 'symlink']);
      else if (child.isDirectory()) { entries.push([name, 'directory']); await visit(full, name); }
      else entries.push([name, 'file', await readFile(full, 'utf8')]);
    }
  }
  await visit(directory);
  return entries;
}

async function assertRejectedUnchanged(target, operation, pattern) {
  const before = await snapshot(target);
  await assert.rejects(operation, pattern);
  assert.deepEqual(await snapshot(target), before);
}

test('rejects project root and its ancestor without changing either', async t => {
  const {parent, root} = await fixture(t);
  await writeFile(path.join(parent, 'sibling.txt'), 'keep me');
  for (const target of [root, parent]) {
    await assertRejectedUnchanged(target,
      () => prepareBuildOutput(root, target), /project root|ancestor/i);
  }
});

test('rejects source and protected project directories unchanged', async t => {
  const {root} = await fixture(t);
  for (const target of [path.join(root, 'apps/web/src'), path.join(root, 'apps/web/public'),
    path.join(root, 'tools')]) {
    await writeFile(path.join(target, 'keep.txt'), 'source data');
    await assertRejectedUnchanged(target,
      () => prepareBuildOutput(root, target), /project tree|protected|only.*dist/i);
  }
});

test('rejects symlink output target and symlink ancestor unchanged', async t => {
  const {parent, root} = await fixture(t);
  const outside = path.join(parent, 'outside');
  await mkdir(outside);
  await writeFile(path.join(outside, 'keep.txt'), 'outside data');
  const targetLink = path.join(parent, 'target-link');
  await symlink(outside, targetLink, 'dir');
  await assert.rejects(prepareBuildOutput(root, targetLink), /symlink/i);
  const ancestorLink = path.join(parent, 'ancestor-link');
  await symlink(parent, ancestorLink, 'dir');
  const nested = path.join(ancestorLink, 'new-output');
  await assert.rejects(prepareBuildOutput(root, nested), /symlink/i);
  assert.equal(await readFile(path.join(outside, 'keep.txt'), 'utf8'), 'outside data');
  assert.deepEqual(await snapshot(parent), [
    ['ancestor-link', 'symlink'], ['outside', 'directory'], ['outside/keep.txt', 'file', 'outside data'],
    ['project', 'directory'], ['project/apps', 'directory'], ['project/apps/web', 'directory'],
    ['project/apps/web/public', 'directory'], ['project/apps/web/src', 'directory'],
    ['project/tools', 'directory'], ['target-link', 'symlink'],
  ]);
});

test('refuses nonempty unmarked arbitrary outputs and malformed markers unchanged', async t => {
  const {parent, root} = await fixture(t);
  const unknown = path.join(parent, 'unknown-output');
  await mkdir(unknown);
  await writeFile(path.join(unknown, 'user.txt'), 'keep me');
  await assertRejectedUnchanged(unknown,
    () => prepareBuildOutput(root, unknown), /unmarked|generated|inspect.*remove/i);
  const malformed = path.join(parent, 'malformed-output');
  await mkdir(malformed);
  await writeFile(path.join(malformed, BUILD_OUTPUT_MARKER), 'not the build marker');
  await writeFile(path.join(malformed, 'user.txt'), 'keep me too');
  await assertRejectedUnchanged(malformed,
    () => prepareBuildOutput(root, malformed), /marker|generated/i);
});

test('unknown build arguments are rejected before any output path is written', async t => {
  const {root} = await fixture(t);
  const target = path.join(root, 'apps/web/dist');
  assert.throws(() => parseBuildArgs(['--outdir', target, '--surprise'], root), /unknown build option/i);
  assert.deepEqual(await snapshot(target), []);
  assert.throws(() => parseBuildArgs(['--outdir', '--surprise'], root), /requires.*path/i);
  assert.deepEqual(await snapshot(target), []);
});

test('default output works when fresh, and isolated quality output gets a path-free marker', async t => {
  const {parent, root} = await fixture(t);
  const defaultOutput = parseBuildArgs([], root);
  assert.equal(defaultOutput, path.join(root, 'apps/web/dist'));
  await prepareBuildOutput(root, defaultOutput);
  assert.equal(await readFile(path.join(defaultOutput, BUILD_OUTPUT_MARKER), 'utf8'), 'mira-web-build-output:v1\n');
  const isolated = path.join(parent, 'quality-run', 'dist');
  await prepareBuildOutput(root, isolated);
  const marker = await readFile(path.join(isolated, BUILD_OUTPUT_MARKER), 'utf8');
  assert.equal(marker, 'mira-web-build-output:v1\n');
  assert.equal(marker.includes(parent), false);
});

test('accepts an empty external output directory without deleting it', async t => {
  const {parent, root} = await fixture(t);
  const output = path.join(parent, 'empty-output');
  await mkdir(output);
  await prepareBuildOutput(root, output);
  assert.equal(await readFile(path.join(output, BUILD_OUTPUT_MARKER), 'utf8'), 'mira-web-build-output:v1\n');
});

test('rebuilds a marked output and removes only its previous generated contents', async t => {
  const {parent, root} = await fixture(t);
  const output = path.join(parent, 'marked-output');
  await mkdir(output);
  await writeFile(path.join(output, BUILD_OUTPUT_MARKER), 'mira-web-build-output:v1\n');
  await mkdir(path.join(output, 'app'));
  await writeFile(path.join(output, 'app/main.js'), 'old generated bundle');
  await prepareBuildOutput(root, output);
  assert.deepEqual(await readdir(output), [BUILD_OUTPUT_MARKER]);
  assert.equal(await readFile(path.join(output, BUILD_OUTPUT_MARKER), 'utf8'), 'mira-web-build-output:v1\n');
});

test('refuses legacy-looking unmarked default dist and unknown additions unchanged', async t => {
  const {root} = await fixture(t);
  const output = path.join(root, 'apps/web/dist');
  await mkdir(path.join(output, 'app'), {recursive: true});
  await mkdir(path.join(output, 'shared'));
  await mkdir(path.join(output, 'licenses'));
  await writeFile(path.join(output, 'app/main.js'), 'bundle');
  await writeFile(path.join(output, 'shared/config.js'), 'compiled');
  await writeFile(path.join(output, 'licenses/THIRD_PARTY_NOTICES.txt'), 'notices');
  await writeFile(path.join(output, 'licenses/pixi.js-8.19.0-MIT.txt'), 'full license');
  await assertRejectedUnchanged(output,
    () => prepareBuildOutput(root, output), /unmarked|generated|inspect.*remove/i);

  await writeFile(path.join(output, 'features.js'), 'unknown');
  await assertRejectedUnchanged(output,
    () => prepareBuildOutput(root, output), /unmarked|generated|inspect.*remove/i);
});
