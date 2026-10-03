import type { AudioProgressRequest, EffectView, ReceiptRequest, SessionView } from '../../shared/generated/contracts.js';

import { validateCueGrants } from '../../shared/cue-contract.js';
import type { AudioOrigin, PlaybackFact } from '../audio/types.js';

/** Browser-owned immediate suppression. A newer server grant cannot clear a local stop. */
export class PresentationGate {
  private activity = 0;
  private presentation = 0;
  private expectedRequest: string | null = null;
  private snapshot: SessionView | null = null;
  private highestPermit = -1;
  private controlFingerprint: string | null = null;
  private knownEffects = new Map<string, string>();
  private consumed = new Set<string>();
  private locallyBlocked = true;
  private audio = new Map<string, { effect: EffectView; rendered: number; terminal: boolean; submitted: boolean }>();

  constructor(private readonly sessionId: string, private readonly clientInstanceId: string) {}

  beginInput(requestId: string): { activity_seq: number; presentation_cutoff: number } {
    this.activity++;
    this.expectedRequest = requestId;
    this.locallyBlocked = true;
    return { activity_seq: this.activity, presentation_cutoff: this.presentation };
  }
  stop(): { activity_seq: number; presentation_cutoff: number } {
    this.activity++;
    this.expectedRequest = null;
    this.locallyBlocked = true;
    return { activity_seq: this.activity, presentation_cutoff: this.presentation };
  }
  block(): void { this.locallyBlocked = true; this.expectedRequest = null; }
  currentActivity(): number { return this.activity; }

  install(next: SessionView): boolean {
    if (next.session_id !== this.sessionId || next.client_instance_id !== this.clientInstanceId) return false;
    if (next.permit_revision < this.highestPermit) return false;
    if (this.snapshot && next.revision < this.snapshot.revision) return false;
    const fingerprint = JSON.stringify([next.activity_seq, next.output_epoch,
      next.request_id, next.active_grants]);
    if (next.permit_revision === this.highestPermit && this.controlFingerprint !== fingerprint) {
      this.locallyBlocked = true;
      throw new Error('Conflicting payload for the same control revision');
    }
    try { validateCueGrants(next.active_grants); }
    catch (error) { this.locallyBlocked = true; throw error; }
    for (const grant of next.active_grants) {
      const identity = JSON.stringify([grant.kind, grant.value, grant.digest, grant.output_epoch, grant.activity_seq,
        grant.cue_id ?? null, grant.cue_speech_id ?? null]);
      const previous = this.knownEffects.get(grant.id);
      if (previous !== undefined && previous !== identity) {
        this.locallyBlocked = true;
        throw new Error('An issued effect identity cannot change content');
      }
      this.knownEffects.set(grant.id, identity);
    }
    this.highestPermit = next.permit_revision;
    this.controlFingerprint = fingerprint;
    // Retain immutable authority, never a caller-owned array/object.
    this.snapshot = Object.freeze({ ...next, active_grants: Object.freeze(next.active_grants.map(grant => Object.freeze({...grant}))) });
    this.locallyBlocked = !(next.activity_seq === this.activity
      && this.expectedRequest !== null && next.request_id === this.expectedRequest
      && (next.phase === 'ready' || next.phase === 'idle'));
    return true;
  }
  isAuthorized(effect: AudioOrigin): boolean {
    return !this.locallyBlocked && this.snapshot !== null
      && effect.output_epoch === this.snapshot.output_epoch
      && effect.activity_seq === this.activity
      && this.snapshot.active_grants.some(grant => grant.id === effect.id && grant.digest === effect.digest && grant.activity_seq === effect.activity_seq && grant.output_epoch === effect.output_epoch);
  }
  allows(effect: EffectView): boolean {
    return this.isAuthorized(effect) && !this.consumed.has(effect.id)
      && this.snapshot!.active_grants.some(grant => grant.id === effect.id && grant.kind === effect.kind && grant.value === effect.value
        && (grant.cue_id ?? null) === (effect.cue_id ?? null)
        && (grant.cue_speech_id ?? null) === (effect.cue_speech_id ?? null))
      && (effect.kind === 'speech' || effect.cue_speech_id == null
        || this.audio.get(effect.cue_speech_id)?.submitted === true);
  }
  claimSpeech(effect: EffectView): boolean {
    if (effect.kind !== 'speech' || !this.allows(effect)) return false;
    this.consumed.add(effect.id);
    this.audio.set(effect.id, {effect: Object.freeze({...effect}), rendered: 0, terminal: false, submitted: false});
    return true;
  }
  /** Open this exact cue only after the sink really submitted its first software source. */
  submitSpeech(fact: PlaybackFact): boolean {
    const state = this.audio.get(fact.origin.id);
    if (!state || state.terminal || state.submitted || fact.stage !== 'submitted'
      || fact.sampleRate !== 24000 || !Number.isSafeInteger(fact.submittedFrames)
      || fact.submittedFrames <= 0 || fact.submittedFrames > 24000 * 300
      || state.effect.digest !== fact.origin.digest || state.effect.output_epoch !== fact.origin.output_epoch
      || state.effect.activity_seq !== fact.origin.activity_seq || !this.isAuthorized(state.effect)) return false;
    state.submitted = true;
    return true;
  }
  audioProgress(fact: PlaybackFact): AudioProgressRequest | null {
    const state = this.audio.get(fact.origin.id);
    if (!state || state.terminal || fact.stage === 'submitted' || fact.origin.activity_seq !== this.activity) return null;
    const effect = state.effect;
    if (effect.digest !== fact.origin.digest || effect.output_epoch !== fact.origin.output_epoch
      || effect.activity_seq !== fact.origin.activity_seq || fact.sampleRate !== 24000
      || !Number.isSafeInteger(fact.renderedFrames) || fact.renderedFrames < state.rendered
      || fact.renderedFrames > 24000 * 300) return null;
    const terminal = fact.stage === 'stopped' || fact.stage === 'failed';
    // Synchronous cutoff termination may follow latch closure, but never a newer activity.
    if (!terminal && (!this.isAuthorized(effect) || fact.renderedFrames === 0)) return null;
    if (fact.stage === 'rendered' && fact.renderedFrames === state.rendered) return null;
    state.rendered = fact.renderedFrames;
    state.terminal = fact.stage !== 'rendered';
    return {effect_id: effect.id, digest: effect.digest, output_epoch: effect.output_epoch,
      activity_seq: effect.activity_seq, presentation_seq: ++this.presentation,
      sample_rate_hz: 24000, rendered_samples: fact.renderedFrames,
      status: fact.stage === 'stopped' ? (fact.reason === 'error' ? 'failed' : 'interrupted') : fact.stage};
  }
  consume(effect: EffectView): ReceiptRequest | null {
    if (effect.kind === 'speech' || !this.allows(effect)) return null;
    this.consumed.add(effect.id);
    this.presentation++;
    return {
      effect_id: effect.id, digest: effect.digest, output_epoch: effect.output_epoch,
      activity_seq: effect.activity_seq, presentation_seq: this.presentation,
    };
  }
}
