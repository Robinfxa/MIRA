import type { CapturedAudio } from './types.js';

/** Compatibility values: headphones enables energy-based interruption; it never attests output hardware. */
export type LocalBargeInMode = 'guarded' | 'headphones';
export interface LocalBargeInResult {
  readonly kind: 'none' | 'candidate' | 'qualified' | 'invalid';
  readonly startSample: number | null;
  readonly endSample: number | null;
}
export interface LocalBargeInObservation {
  readonly playbackBusy: boolean;
  readonly noiseFloor: number;
}

const NONE: LocalBargeInResult = Object.freeze({kind: 'none', startSample: null, endSample: null});
const INVALID: LocalBargeInResult = Object.freeze({kind: 'invalid', startSample: null, endSample: null});
const ACTIVE_SAMPLES = 2560;
const QUIET_SAMPLES = 3200;

/** Sound-energy qualification only. Enabled mode is neither speech identity nor echo proof. */
export class LocalBargeInDetector {
  private nextSequence = 0;
  private nextSample = 0;
  private activeSamples = 0;
  private quietSamples = 0;
  private candidateStart: number | null = null;
  private latched = false;
  private invalid = false;
  constructor(readonly mode: LocalBargeInMode = 'guarded') {
    if (mode !== 'guarded' && mode !== 'headphones') throw new RangeError('Invalid local interruption mode');
  }
  observe(chunk: CapturedAudio, observation: LocalBargeInObservation): LocalBargeInResult {
    if (this.invalid) return INVALID;
    const bytes = chunk.pcm16le;
    const age = chunk.deliveryLagMilliseconds;
    if (!(bytes instanceof Uint8Array) || bytes.length < 2 || bytes.length > 3200 || bytes.length % 2 !== 0
      || chunk.sampleRate !== 16000 || chunk.channels !== 1
      || !Number.isSafeInteger(chunk.sequence) || chunk.sequence !== this.nextSequence
      || !Number.isSafeInteger(chunk.startSample) || chunk.startSample !== this.nextSample
      || !Number.isSafeInteger(chunk.endSample) || chunk.endSample !== chunk.startSample + bytes.length / 2
      || (age !== undefined && (!Number.isFinite(age) || age < 0 || age > 200))
      || typeof observation.playbackBusy !== 'boolean' || !Number.isFinite(observation.noiseFloor)) {
      this.invalid = true; this.activeSamples = 0; this.candidateStart = null;
      return INVALID;
    }
    this.nextSequence++; this.nextSample = chunk.endSample;
    if (this.mode === 'guarded') return NONE;
    const samples = bytes.length / 2;
    const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let energy = 0;
    for (let index = 0; index < samples; index++) {
      const value = data.getInt16(index * 2, true); energy += value * value;
    }
    const rms = Math.sqrt(energy / samples);
    const floor = Math.max(40, Math.min(300, observation.noiseFloor));
    if (rms < Math.max(180, floor * 2)) {
      this.quietSamples = Math.min(QUIET_SAMPLES, this.quietSamples + samples);
      if (this.quietSamples >= QUIET_SAMPLES) this.latched = false;
    } else this.quietSamples = 0;
    if (!observation.playbackBusy || this.latched || rms < Math.max(600, floor * 4)) {
      this.activeSamples = 0; this.candidateStart = null;
      return NONE;
    }
    this.candidateStart ??= chunk.startSample;
    this.activeSamples = Math.min(ACTIVE_SAMPLES, this.activeSamples + samples);
    const qualified = this.activeSamples >= ACTIVE_SAMPLES;
    const result: LocalBargeInResult = Object.freeze({kind: qualified ? 'qualified' : 'candidate',
      startSample: this.candidateStart, endSample: chunk.endSample});
    if (qualified) { this.latched = true; this.activeSamples = 0; this.candidateStart = null; }
    return result;
  }
  /** Only a fresh lease may reset. Recognition child-stream rotation must retain sample history. */
  reset(): void {
    this.nextSequence = 0; this.nextSample = 0; this.activeSamples = 0; this.quietSamples = 0;
    this.candidateStart = null; this.latched = false; this.invalid = false;
  }
}
