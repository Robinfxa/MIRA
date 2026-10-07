import type { SceneAction, SceneExpression, ScenePhase, SceneState } from './scene-state.js';

export interface CharacterSize { readonly width: number; readonly height: number; }
export interface CharacterPoint { readonly x: number; readonly y: number; }
export interface CharacterFrameAsset {
  readonly src: string;
  readonly pixelSize: CharacterSize;
  readonly sourceAnchor: CharacterPoint;
  readonly sha256: string;
}
export interface CharacterManifest {
  readonly schemaVersion: 1;
  readonly logicalSize: CharacterSize;
  readonly logicalRootAnchor: CharacterPoint;
  readonly base: CharacterFrameAsset;
  readonly expressionVariants: Readonly<Partial<Record<SceneExpression, CharacterFrameAsset>>>;
  readonly actionVariants: Readonly<Partial<Record<Exclude<SceneAction, 'camera_ready'>,
    Readonly<Partial<Record<SceneExpression, CharacterFrameAsset>>>>>>;
}
export interface CharacterFrameLayout {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly scale: number;
}

const PHASES: readonly ScenePhase[] = ['idle', 'listening', 'thinking', 'speaking'];
const EXPRESSIONS: readonly SceneExpression[] = ['calm', 'warm', 'curious', 'reflective'];
const ACTIONS: readonly SceneAction[] = ['camera_ready', 'camera_lowered', 'look_at_rain'];
const EXPRESSION_VARIANTS: readonly SceneExpression[] = ['warm', 'curious', 'reflective'];
const ACTION_VARIANTS: readonly Exclude<SceneAction, 'camera_ready'>[] = ['camera_lowered', 'look_at_rain'];
const fail = (): never => { throw new Error('Invalid local character manifest'); };
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const exactKeys = (value: Record<string, unknown>, expected: readonly string[]): boolean =>
  Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key));
const positiveInteger = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0;
const point = (value: unknown): value is CharacterPoint => isRecord(value)
  && typeof value.x === 'number' && Number.isFinite(value.x)
  && typeof value.y === 'number' && Number.isFinite(value.y);

function parseSize(value: unknown): CharacterSize {
  if (!isRecord(value) || !exactKeys(value, ['width', 'height'])
      || !positiveInteger(value.width) || !positiveInteger(value.height)
      || value.width >= 2048 || value.height >= 2048) return fail();
  return {width: value.width, height: value.height};
}

function parseFrame(value: unknown): CharacterFrameAsset {
  if (!isRecord(value) || !exactKeys(value, ['src', 'pixelSize', 'sourceAnchor', 'sha256'])
      || typeof value.src !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,100}\.png$/.test(value.src)
      || typeof value.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.sha256)
      || !point(value.sourceAnchor)) return fail();
  const pixelSize = parseSize(value.pixelSize);
  // Every generated full-frame asset shares the same bottom-centre registration.
  if (value.sourceAnchor.x !== pixelSize.width / 2 || value.sourceAnchor.y !== pixelSize.height) return fail();
  return {src: value.src, sha256: value.sha256, pixelSize,
    sourceAnchor: {x: value.sourceAnchor.x, y: value.sourceAnchor.y}};
}

function parseAssetMap<T extends string>(value: unknown, keys: readonly T[]): Partial<Record<T, CharacterFrameAsset>> {
  if (!isRecord(value) || Object.keys(value).some(key => !keys.includes(key as T))) return fail();
  const parsed: Partial<Record<T, CharacterFrameAsset>> = {};
  for (const key of keys) {
    const entry = value[key];
    if (entry !== undefined) parsed[key] = parseFrame(entry);
  }
  return parsed;
}

export function parseCharacterManifest(value: unknown): CharacterManifest {
  if (!isRecord(value) || value.schemaVersion !== 1
      || !exactKeys(value, ['schemaVersion', 'logicalSize', 'logicalRootAnchor', 'base', 'expressionVariants', 'actionVariants'])
      || !point(value.logicalRootAnchor)) return fail();
  const logicalSize = parseSize(value.logicalSize);
  if (logicalSize.width !== 560 || logicalSize.height !== 720
      || value.logicalRootAnchor.x !== 280 || value.logicalRootAnchor.y !== 720) return fail();
  const base = parseFrame(value.base);
  const expressionVariants = parseAssetMap(value.expressionVariants, EXPRESSION_VARIANTS);
  const rawActions = value.actionVariants;
  if (!isRecord(rawActions) || Object.keys(rawActions).some(key => !ACTION_VARIANTS.includes(key as typeof ACTION_VARIANTS[number]))) return fail();
  const actionVariants: Partial<Record<Exclude<SceneAction, 'camera_ready'>,
    Partial<Record<SceneExpression, CharacterFrameAsset>>>> = {};
  for (const action of ACTION_VARIANTS) {
    const frames = parseAssetMap(rawActions[action], EXPRESSIONS);
    if (EXPRESSIONS.some(expression => frames[expression] === undefined)) return fail();
    actionVariants[action] = frames;
  }
  if (EXPRESSION_VARIANTS.some(expression => expressionVariants[expression] === undefined)) return fail();
  const all: CharacterFrameAsset[] = [base, ...Object.values(expressionVariants),
    ...Object.values(actionVariants).flatMap(group => Object.values(group ?? {}))];
  if (new Set(all.map(frame => frame.src)).size !== all.length) return fail();
  return {schemaVersion: 1, logicalSize, logicalRootAnchor: {x: 280, y: 720}, base,
    expressionVariants, actionVariants};
}

/** Keep a fixed bottom-centre anchor and uniform per-frame scale; never crop or stretch. */
export function fitCharacterFrame(frame: CharacterFrameAsset, manifest: CharacterManifest): CharacterFrameLayout {
  const scale = manifest.logicalSize.height / frame.pixelSize.height;
  return {
    x: manifest.logicalRootAnchor.x - frame.sourceAnchor.x * scale,
    y: manifest.logicalRootAnchor.y - frame.sourceAnchor.y * scale,
    width: frame.pixelSize.width * scale,
    height: frame.pixelSize.height * scale,
    scale,
  };
}

/** Exact action/expression composites only. Phase is retained by the executor, not inferred from a static frame. */
export function chooseCharacterFrame(manifest: CharacterManifest, state: Pick<SceneState, 'phase' | 'expression' | 'action'>): CharacterFrameAsset | null {
  if (!PHASES.includes(state.phase) || !EXPRESSIONS.includes(state.expression) || !ACTIONS.includes(state.action)) return null;
  if (state.action === 'camera_ready') return state.expression === 'calm'
    ? manifest.base : manifest.expressionVariants[state.expression] ?? null;
  return manifest.actionVariants[state.action]?.[state.expression] ?? null;
}
