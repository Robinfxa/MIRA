import type { EffectView } from './generated/contracts.js';

/** Bounded application cue metadata. No text equality or inferred timing association. */
export function validateCueFields(effect: EffectView): void {
  for (const value of [effect.cue_id, effect.cue_speech_id]) {
    if (value != null && (typeof value !== 'string' || value.length === 0 || value.length > 128)) {
      throw new Error('Invalid presentation cue metadata');
    }
  }
  if (effect.cue_speech_id != null && effect.cue_id == null) throw new Error('Missing presentation cue identity');
  const chunk = effect.caption_chunk;
  if (chunk != null) {
    if (typeof chunk !== 'object' || Array.isArray(chunk)
      || Object.keys(chunk).sort().join(',') !== 'end,group_id,index,source_sha256,start,total'
      || effect.kind !== 'subtitle' || effect.cue_speech_id != null
      || typeof chunk.group_id !== 'string' || !/^[0-9a-f-]{36}$/.test(chunk.group_id)
      || typeof chunk.source_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(chunk.source_sha256)
      || ![chunk.index, chunk.start, chunk.end, chunk.total].every(Number.isSafeInteger)
      || chunk.index < 0 || chunk.index > 3 || chunk.start < 0 || chunk.start >= chunk.end
      || chunk.end > chunk.total || chunk.total > 4096
      || (chunk.index === 0) !== (chunk.start === 0)
      || Array.from(effect.value).length !== chunk.end - chunk.start) {
      throw new Error('Invalid original caption chunk');
    }
  }

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
  const captionGroups = new Map<string, EffectView[]>();
  for (const effect of effects) {
    const chunk = effect.caption_chunk;
    if (!chunk) continue;
    const group = captionGroups.get(chunk.group_id) ?? [];
    const previous = group.at(-1);
    if ((!previous && chunk.index !== 0) || (previous && (
      previous.caption_chunk!.index + 1 !== chunk.index || previous.caption_chunk!.end !== chunk.start
      || previous.caption_chunk!.total !== chunk.total || previous.caption_chunk!.source_sha256 !== chunk.source_sha256
      || previous.activity_seq !== effect.activity_seq || previous.output_epoch !== effect.output_epoch))) {
      throw new Error('Noncontiguous original caption chunks');
    }
    group.push(effect); captionGroups.set(chunk.group_id, group);
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
