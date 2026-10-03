import type { EffectView } from './generated/contracts.js';

/** Bounded application cue metadata. No text equality or inferred timing association. */
export function validateCueFields(effect: EffectView): void {
  for (const value of [effect.cue_id, effect.cue_speech_id]) {
    if (value != null && (typeof value !== 'string' || value.length === 0 || value.length > 128)) {
      throw new Error('Invalid presentation cue metadata');
    }
  }
  if (effect.cue_speech_id != null && effect.cue_id == null) throw new Error('Missing presentation cue identity');
}

/** Active grants are complete sets; presented history can intentionally omit a speech peer. */
export function validateCueGrants(effects: readonly EffectView[]): void {
  const ids = new Map<string, EffectView>();
  const cues = new Map<string, EffectView[]>();
  for (const effect of effects) {
    validateCueFields(effect);
    if (ids.has(effect.id)) throw new Error('Duplicate presentation effect identity');
    ids.set(effect.id, effect);
    if (effect.cue_id != null) {
      const group = cues.get(effect.cue_id) ?? [];
      group.push(effect); cues.set(effect.cue_id, group);
    }
  }
  // Only an isolated legacy speech has an unambiguous meaning. Never guess which text belongs to it.
  const speech = effects.filter(effect => effect.kind === 'speech');
  if (speech.length && effects.some(effect => effect.cue_id == null)
      && !(effects.length === 1 && speech[0]!.cue_id == null)) {
    throw new Error('Ambiguous legacy speech cue');
  }
  for (const group of cues.values()) {
    const first = group[0]!;
    if (group.length > 8 || group.some(effect => effect.cue_speech_id !== first.cue_speech_id
      || effect.output_epoch !== first.output_epoch || effect.activity_seq !== first.activity_seq)) {
      throw new Error('Conflicting presentation cue metadata');
    }
    const spoken = group.filter(effect => effect.kind === 'speech');
    if (first.cue_speech_id == null) {
      if (spoken.length) throw new Error('Speech cue requires its exact speech identity');
      continue;
    }
    const peer = ids.get(first.cue_speech_id);
    if (spoken.length !== 1 || !peer || peer !== spoken[0]
      || peer.cue_speech_id !== peer.id || group.filter(effect => effect.kind === 'subtitle').length > 1) {
      throw new Error('Ambiguous or missing speech cue peer');
    }
  }
}
