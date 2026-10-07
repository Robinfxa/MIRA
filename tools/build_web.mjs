import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {copyFile, cp, lstat, mkdir, readFile, readdir, rm, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const BUILD_OUTPUT_MARKER = '.mira-web-build-output';
const BUILD_OUTPUT_MARKER_CONTENT = 'mira-web-build-output:v1\n';

export function parseBuildArgs(args, projectRoot = root) {
  let outdir = path.join(path.resolve(projectRoot), 'apps/web/dist');
  for (let index = 0; index < args.length; index++) {
    if (args[index] !== '--outdir') throw new Error(`Unknown build option: ${args[index]}`);
    const value = args[index + 1];
    if (!value || value.startsWith('--')) throw new Error('--outdir requires a path');
    outdir = path.resolve(value);
    index++;
  }
  return outdir;
}

function isWithin(candidate, parent) {
  const relative = path.relative(parent, candidate);
  return relative === '' || (relative !== '..' && !relative.startsWith(`..${path.sep}`)
    && !path.isAbsolute(relative));
}

async function assertNoSymlinkComponents(target) {
  const resolved = path.resolve(target);
  const {root: filesystemRoot} = path.parse(resolved);
  const segments = resolved.slice(filesystemRoot.length).split(path.sep).filter(Boolean);
  let current = filesystemRoot;
  for (const segment of segments) {
    current = path.join(current, segment);
    let info;
    try {
      info = await lstat(current);
    } catch (error) {
      if (error.code === 'ENOENT') return;
      throw error;
    }
    if (info.isSymbolicLink()) throw new Error(`Refusing build output through symlink: ${current}`);
    if (current !== resolved && !info.isDirectory()) {
      throw new Error(`Refusing build output because an ancestor is not a directory: ${current}`);
    }
  }
}

async function readExistingDirectory(target) {
  try {
    const info = await lstat(target);
    if (!info.isDirectory() || info.isSymbolicLink()) {
      throw new Error(`Refusing build output that is not a real directory: ${target}`);
    }
    return await readdir(target);
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

/**
 * Validate and prepare a disposable bundle output. Existing contents are removed only when a
 * path-free marker proves prior ownership. Missing or empty output paths are safe to claim.
 */
export async function prepareBuildOutput(projectRoot, requestedOutdir) {
  const project = path.resolve(projectRoot);
  const outdir = path.resolve(requestedOutdir);
  const defaultOutput = path.join(project, 'apps/web/dist');
  if (isWithin(project, outdir)) {
    throw new Error(`Refusing to build into the project root or an ancestor: ${outdir}`);
  }
  if (isWithin(outdir, project) && outdir !== defaultOutput) {
    throw new Error(`Refusing an in-project or protected output path: only apps/web/dist is a build destination (${outdir})`);
  }
  await assertNoSymlinkComponents(outdir);
  const entries = await readExistingDirectory(outdir);
  if (entries === null) {
    await mkdir(outdir, {recursive: true});
  } else {
    const markerPath = path.join(outdir, BUILD_OUTPUT_MARKER);
    if (entries.includes(BUILD_OUTPUT_MARKER)) {
      const markerInfo = await lstat(markerPath);
      if (!markerInfo.isFile() || markerInfo.isSymbolicLink()
          || await readFile(markerPath, 'utf8') !== BUILD_OUTPUT_MARKER_CONTENT) {
        throw new Error(`Refusing an output with an invalid generated-output marker: ${outdir}`);
      }
      await rm(outdir, {recursive: true, force: false});
      await mkdir(outdir, {recursive: false});
    } else if (entries.length === 0) {
      // An empty directory contains no user files to remove; claim it for this build.
    } else {
      throw new Error(`Refusing nonempty unmarked build output: ${outdir}. Inspect and move or remove it yourself, then retry.`);
    }
  }
  await writeFile(path.join(outdir, BUILD_OUTPUT_MARKER), BUILD_OUTPUT_MARKER_CONTENT, {flag: 'wx'});
  return outdir;
}

async function verifyArtwork() {
  const sceneRoot = path.join(root, 'apps/web/public/scene');
  const manifest = JSON.parse(await readFile(path.join(sceneRoot, 'mira_manifest.json'), 'utf8'));
  const frames = [manifest.base, ...Object.values(manifest.expressionVariants ?? {}),
    ...Object.values(manifest.actionVariants ?? {}).flatMap(value => Object.values(value ?? {}))];
  if (!frames.length || frames.length > 16) throw new Error('Character frame manifest is outside the supported bound');
  let totalBytes = 0;
  for (const frame of frames) {
    if (!frame || typeof frame.src !== 'string' || path.basename(frame.src) !== frame.src
        || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,100}\.png$/.test(frame.src)
        || !Number.isSafeInteger(frame.pixelSize?.width) || !Number.isSafeInteger(frame.pixelSize?.height)
        || typeof frame.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(frame.sha256)) {
      throw new Error('Character frame manifest contains an invalid local asset reference');
    }
    const bytes = await readFile(path.join(sceneRoot, frame.src));
    if (bytes.byteLength > 3 * 1024 * 1024 || bytes.length < 29
        || bytes.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a'
        || bytes.readUInt32BE(16) !== frame.pixelSize?.width
        || bytes.readUInt32BE(20) !== frame.pixelSize?.height
        || bytes[25] !== 6
        || frame.pixelSize.width >= 2048 || frame.pixelSize.height >= 2048
        || createHash('sha256').update(bytes).digest('hex') !== frame.sha256) {
      throw new Error(`Character frame integrity check failed: ${frame.src}`);
    }
    totalBytes += bytes.byteLength;
  }
  if (totalBytes > 32 * 1024 * 1024) throw new Error('Character artwork exceeds the compressed asset budget');
}

const runtimeLicensePackages = [
  ['pixi.js', '8.19.0', 'MIT', 'pixi.js-8.19.0-MIT.txt', 'LICENSE'],
  ['@pixi/colord', '2.9.6', 'MIT', 'pixi-colord-2.9.6-MIT.txt', null],
  ['@xmldom/xmldom', '0.8.15', 'MIT', 'xmldom-0.8.15-MIT.txt', 'LICENSE'],
  ['earcut', '3.2.4', 'ISC', 'earcut-3.2.4-ISC.txt', 'LICENSE'],
  ['eventemitter3', '5.0.4', 'MIT', 'eventemitter3-5.0.4-MIT.txt', 'LICENSE'],
  ['gifuct-js', '2.1.2', 'MIT', 'gifuct-js-2.1.2-MIT.txt', 'LICENSE'],
  ['ismobilejs', '1.1.1', 'MIT', 'ismobilejs-1.1.1-MIT.txt', 'LICENSE'],
  ['js-binary-schema-parser', '2.0.3', 'MIT', 'js-binary-schema-parser-2.0.3-MIT.txt', 'LICENSE'],
  ['parse-svg-path', '0.2.0', 'MIT', 'parse-svg-path-0.2.0-MIT.txt', 'LICENSE'],
  ['tiny-lru', '11.4.7', 'BSD-3-Clause', 'tiny-lru-11.4.7-BSD-3-Clause.txt', 'LICENSE'],
];

export async function main(args = process.argv.slice(2)) {
  const outdir = parseBuildArgs(args, root);
  await verifyArtwork();
  for (const [name, version] of [['pixi.js', '8.19.0'], ['esbuild', '0.28.2']]) {
    const packageInfo = JSON.parse(await readFile(path.join(root, 'node_modules', name, 'package.json'), 'utf8'));
    if (packageInfo.version !== version || packageInfo.license !== 'MIT') {
      throw new Error(`Locked browser dependency is missing or changed: ${name}`);
    }
  }
  const noticeRoot = path.join(root, 'apps/web/public/licenses');
  const noticeIndex = await readFile(path.join(noticeRoot, 'THIRD_PARTY_NOTICES.txt'), 'utf8');
  for (const [name, version, license, filename, upstreamLicenseName] of runtimeLicensePackages) {
    const packageInfo = JSON.parse(await readFile(path.join(root, 'node_modules', name, 'package.json'), 'utf8'));
    if (packageInfo.version !== version || packageInfo.license !== license
        || !noticeIndex.includes(`${name} ${version} — ${license} — ${filename}`)) {
      throw new Error(`Runtime dependency notice is missing or mismatched: ${name}@${version}`);
    }
    const includedText = await readFile(path.join(noticeRoot, filename));
    if (includedText.byteLength < 700) throw new Error(`Full license text is missing: ${filename}`);
    if (upstreamLicenseName) {
      const upstreamText = await readFile(path.join(root, 'node_modules', name, upstreamLicenseName));
      if (!includedText.equals(upstreamText)) throw new Error(`License text differs from locked package: ${name}`);
    }
  }
  const tsc = path.join(root, 'node_modules/typescript/bin/tsc');
  const {build} = await import('esbuild');
  await prepareBuildOutput(root, outdir);
  await cp(path.join(root, 'apps/web/public/licenses'), path.join(outdir, 'licenses'), {recursive: true});
  execFileSync(process.execPath, [tsc, '-p', 'apps/web/tsconfig.json', '--outDir', outdir, '--sourceMap', 'false'], {cwd: root, stdio: 'inherit'});
  await copyFile(path.join(outdir, 'app/main.js'), path.join(outdir, 'app/main-source.js'));
  await build({
    absWorkingDir: root,
    entryPoints: ['apps/web/src/app/main.ts'],
    bundle: true,
    splitting: true,
    format: 'esm',
    platform: 'browser',
    target: ['es2022'],
    outdir,
    entryNames: 'app/main',
    chunkNames: 'app/chunks/[name]-[hash]',
    sourcemap: false,
    minify: true,
    legalComments: 'linked',
    treeShaking: true,
  });
  await build({
    absWorkingDir: root,
    entryPoints: ['apps/web/src/local-memory/main.ts'],
    bundle: true,
    splitting: false,
    format: 'esm',
    platform: 'browser',
    target: ['es2022'],
    outfile: path.join(outdir, 'local-memory/main.js'),
    sourcemap: false,
    minify: true,
    legalComments: 'linked',
    treeShaking: true,
  });
  console.log(`Built local browser bundle: ${path.relative(root, path.join(outdir, 'app/main.js'))}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
