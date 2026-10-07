import type { AudioProgressRequest, EffectView, ReceiptRequest, SessionView } from '../../shared/generated/contracts.js';

import { validateCueGrants } from '../../shared/cue-contract.js';
import { isPhotoValue, generatedPhotoIdentity } from '../../shared/photo-value.js';
import type { AudioOrigin, PlaybackFact } from '../audio/types.js';

/** Browser-owned immediate suppression. A newer server grant cannot clear a local stop. */
export class PresentationGate {
  private activity = 0;
  private photoDismissedThroughActivity = -1;
  private imageDismissedThroughActivity = -1;
  private imagesOnly = false;
  private readonly dismissedPhotoEffects = new Set<string>();
  private presentation = 0;
  private expectedRequest: string | null = null;
  private snapshot: SessionView | null = null;
  private highestPermit = -1;
  private highestOutputEpoch = -1;
  private controlFingerprint: string | null = null;
  private knownEffects = new Map<string, string>();
  private consumed = new Set<string>();
  private locallyBlocked = true;
  private speechFailureText: ReadonlySet<string> | null = null;
  private audio = new Map<string, { effect: EffectView; rendered: number; terminal: boolean; submitted: boolean }>();

  constructor(private readonly sessionId: string, private readonly clientInstanceId: string) {}

  private advanceActivity(): void {
    this.activity++;
    this.imagesOnly=false;this.dismissedPhotoEffects.clear();
    // Only current-activity grants enter these collections. The controller blocks
    // and synchronously stops its sink before advancing activity, so its exact
    // terminal prefix already owns a presentation sequence and queued receipt.
    // No callback from a retired activity may allocate another receipt. Keep the
    // global presentation/control watermarks, but release these stale identities.
    this.knownEffects.clear();
    this.consumed.clear();
    this.audio.clear();
    this.speechFailureText = null;
  }

  beginInput(requestId: string): { activity_seq: number; presentation_cutoff: number } {
    this.advanceActivity();
    this.expectedRequest = requestId;
    this.locallyBlocked = true;
    return { activity_seq: this.activity, presentation_cutoff: this.presentation };
  }
  stop(): { activity_seq: number; presentation_cutoff: number } {
    this.advanceActivity();
    this.expectedRequest = null;
    this.locallyBlocked = true;
    return { activity_seq: this.activity, presentation_cutoff: this.presentation };
  }
  block(): void { this.locallyBlocked = true; this.expectedRequest = null; }
  currentActivity(): number { return this.activity; }
  dismissPhoto(target: 'display'|'fixed_photo'|'image_job'|'all_photos'='all_photos', effectId?: string): {presentation_cutoff:number} {
    if (target==='fixed_photo' || target==='all_photos') this.photoDismissedThroughActivity=this.activity;
    if (target==='image_job' || target==='all_photos') this.imageDismissedThroughActivity=this.activity;
    if (target==='display' && effectId) this.dismissedPhotoEffects.add(effectId);
    return {presentation_cutoff:this.presentation};
  }
  /** A reply-only stop never opens old text/audio/control grants. */
  resumeBackgroundImages(): void {
    if (!this.snapshot || this.snapshot.activity_seq!==this.activity || !this.snapshot.request_id) return;
    this.expectedRequest=this.snapshot.request_id;this.imagesOnly=true;
    this.locallyBlocked=!['ready','idle'].includes(this.snapshot.phase);
  }

  install(next: SessionView): boolean {
    if (next.session_id !== this.sessionId || next.client_instance_id !== this.clientInstanceId) return false;
    if (next.permit_revision < this.highestPermit) return false;
    if (next.output_epoch < this.highestOutputEpoch) return false;
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
      // Stale snapshots still carry revocation control, never local receipt
      // authority. They must not refill history retired by Stop or newer input.
      if (grant.activity_seq !== this.activity) continue;
      const identity = JSON.stringify([grant.kind, grant.value, grant.digest, grant.output_epoch, grant.activity_seq,
        grant.cue_id ?? null, grant.cue_speech_id ?? null, grant.caption_chunk ?? null]);
      const previous = this.knownEffects.get(grant.id);
      if (previous !== undefined && previous !== identity) {
        this.locallyBlocked = true;
        throw new Error('An issued effect identity cannot change content');
      }
      this.knownEffects.set(grant.id, identity);
    }
    this.highestPermit = next.permit_revision;
    this.highestOutputEpoch = next.output_epoch;
    this.controlFingerprint = fingerprint;
    // Retain immutable authority, never a caller-owned array/object.
    this.snapshot = Object.freeze({ ...next, active_grants: Object.freeze(next.active_grants.map(grant => Object.freeze({...grant, ...(grant.caption_chunk == null ? {} : {caption_chunk: Object.freeze({...grant.caption_chunk})})}))) });
    this.locallyBlocked = !(next.activity_seq === this.activity
      && this.expectedRequest !== null && next.request_id === this.expectedRequest
      && (next.phase === 'ready' || next.phase === 'idle'));
    return true;
  }
  /** Restrict this local turn to text already granted independently of audio. */
  preserveTextAfterSpeechFailure(origin: AudioOrigin): boolean {
    if (!this.isAuthorized(origin) || !this.snapshot?.active_grants.some(effect =>
      effect.id === origin.id && effect.kind === 'speech')) return false;
    const text = this.snapshot.active_grants.filter(effect => effect.kind === 'subtitle'
      && effect.cue_id != null && effect.cue_speech_id == null);
    if (!text.length) return false;
    this.speechFailureText = new Set(text.map(effect => effect.id));
    return true;
  }
  isAuthorized(effect: AudioOrigin): boolean {
    return !this.locallyBlocked && this.snapshot !== null
      && (!this.imagesOnly || this.snapshot.active_grants.some(e=>e.id===effect.id && e.kind==='media' && generatedPhotoIdentity(e.value)))
      && (this.speechFailureText === null || this.speechFailureText.has(effect.id))
      && effect.output_epoch === this.snapshot.output_epoch
      && effect.activity_seq === this.activity
      && this.snapshot.active_grants.some(grant => grant.id === effect.id && grant.digest === effect.digest && grant.activity_seq === effect.activity_seq && grant.output_epoch === effect.output_epoch);
  }
  allows(effect: EffectView): boolean {
    return this.isAuthorized(effect) && !this.consumed.has(effect.id)
      && !this.dismissedPhotoEffects.has(effect.id)
      && !(effect.kind==='media' && isPhotoValue(effect.value) && effect.activity_seq <=
        (generatedPhotoIdentity(effect.value) ? this.imageDismissedThroughActivity : this.photoDismissedThroughActivity))
      && this.snapshot!.active_grants.some(grant => grant.id === effect.id && grant.kind === effect.kind && grant.value === effect.value
        && (grant.cue_id ?? null) === (effect.cue_id ?? null)
        && (grant.cue_speech_id ?? null) === (effect.cue_speech_id ?? null)
        && JSON.stringify(grant.caption_chunk ?? null) === JSON.stringify(effect.caption_chunk ?? null))
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
