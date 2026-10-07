import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const publicLicenses = resolve('apps/web/public/licenses');
const builtLicenses = resolve(process.env.MIRA_TEST_WEB_DIST ?? 'apps/web/dist', 'licenses');

test('PixiJS and its locked runtime dependency license texts ship with the bundle', async () => {
  const index = await readFile(resolve(publicLicenses, 'THIRD_PARTY_NOTICES.txt'), 'utf8');
  const expected = [
    'pixi.js-8.19.0-MIT.txt',
    'pixi-colord-2.9.6-MIT.txt',
    'xmldom-0.8.15-MIT.txt',
    'earcut-3.2.4-ISC.txt',
    'eventemitter3-5.0.4-MIT.txt',
    'gifuct-js-2.1.2-MIT.txt',
    'ismobilejs-1.1.1-MIT.txt',
    'js-binary-schema-parser-2.0.3-MIT.txt',
    'parse-svg-path-0.2.0-MIT.txt',
    'tiny-lru-11.4.7-BSD-3-Clause.txt',
  ];
  for (const filename of expected) {
    assert.ok(index.includes(filename), `notice index must list ${filename}`);
    const license = await readFile(resolve(publicLicenses, filename), 'utf8');
    assert.ok(license.trim().length >= 700, `${filename} must contain a full license text`);
    assert.equal(await readFile(resolve(builtLicenses, filename), 'utf8'), license);
  }
  const publicFiles = (await readdir(publicLicenses)).sort();
  const builtFiles = (await readdir(builtLicenses)).sort();
  assert.deepEqual(builtFiles, publicFiles);
  const pixi = await readFile(resolve(publicLicenses, expected[0]), 'utf8');
  assert.match(pixi, /Copyright \(c\) 2013-2023 Mathew Groves, Chad Engler/);
  assert.match(pixi, /Permission is hereby granted, free of charge/);
  assert.match(pixi, /THE SOFTWARE IS PROVIDED "AS IS"/);
});

test('application exposes a license link for its bundled JavaScript', async () => {
  const html = await readFile(resolve('apps/web/index.html'), 'utf8');
  assert.match(html, /rel="license"[^>]+href="\/assets\/licenses\/THIRD_PARTY_NOTICES\.txt"/);
});
