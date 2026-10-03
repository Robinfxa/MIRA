import type { EffectView } from '../../shared/generated/contracts.js';

export type ScenePhase = 'idle' | 'listening' | 'thinking' | 'speaking';
export type SceneExpression = 'calm' | 'warm' | 'curious' | 'reflective';
export type SceneAction = 'camera_ready' | 'camera_lowered' | 'look_at_rain';
export type SceneEnvironment = 'cafe' | 'rain_window' | 'cafe_warm';

/** Presented visual facts only. Admission and output identity belong to PresentationGate. */
export interface SceneState {
  readonly phase: ScenePhase;
  readonly expression: SceneExpression;
  readonly action: SceneAction;
  readonly environment: SceneEnvironment;
  readonly photoVisible: boolean;
  readonly subtitle: string;
}

export function initialSceneState(): SceneState {
  return {
    phase: 'idle', expression: 'calm', action: 'camera_ready', environment: 'cafe',
    photoVisible: false, subtitle: '窗外还在下雨。和 MIRA 打个招呼吧。',
  };
}

/** No timers, asset fetching, HTML parsing, audio, or permission decisions. */
export function reduceSceneEffect(state: SceneState, effect: EffectView): SceneState {
  switch (effect.kind) {
    case 'subtitle': return { ...state, subtitle: effect.value };
    case 'pose':
      switch (effect.value) {
        case 'camera_lowered': return { ...state, action: 'camera_lowered', expression: 'warm' };
        case 'camera_ready': return { ...state, action: 'camera_ready', expression: 'calm' };
        case 'look_at_rain': return { ...state, action: 'look_at_rain', expression: 'reflective' };
        case 'face_calm': return { ...state, expression: 'calm' };
        case 'face_warm': return { ...state, expression: 'warm' };
        case 'face_curious': return { ...state, expression: 'curious' };
        case 'face_reflective': return { ...state, expression: 'reflective' };
      }
      break;
    case 'scene':
      switch (effect.value) {
        case 'rain_window': return { ...state, environment: 'rain_window', action: 'look_at_rain', expression: 'reflective' };
        case 'cafe': return { ...state, environment: 'cafe', action: 'camera_ready', expression: 'calm' };
        case 'cafe_warm': return { ...state, environment: 'cafe_warm', expression: 'warm' };
      }
      break;
    case 'media':
      // The legacy fixture identity now has an original local illustration, never an external URL.
      if (effect.value === 'trip_photo_placeholder' || effect.value === 'trip_photo') {
        return { ...state, photoVisible: true, expression: 'warm' };
      }
      break;
  }
  throw new Error(`Unsupported scene ${effect.kind} effect`);
}
