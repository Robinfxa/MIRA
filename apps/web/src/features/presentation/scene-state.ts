import type { EffectView } from '../../shared/generated/contracts.js';
import { generatedPhotoIdentity } from '../../shared/photo-value.js';

export type ScenePhase = 'idle' | 'listening' | 'thinking' | 'speaking';
export type SceneExpression = 'calm' | 'warm' | 'curious' | 'reflective';
export type SceneAction = 'camera_raise' | 'camera_ready' | 'camera_lowered' | 'look_at_rain';
export type SceneEnvironment = 'cafe' | 'rain_window' | 'cafe_warm';
export type SceneRigOutfit = 'outfit_black_jacket' | 'outfit_cream_inner_only' | 'outfit_amber_raincoat';
export type SceneRigEmotion = 'emotion_normal' | 'emotion_guarded' | 'emotion_happy' | 'emotion_shy';
export type SceneRigAccessory = 'accessory_camera_clip' | 'accessory_star_clip';

/** Presented visual facts only. Admission and output identity belong to PresentationGate. */
export interface SceneState {
  readonly phase: ScenePhase;
  readonly expression: SceneExpression;
  /** Last committed endpoint; optional renderer motion separately describes a live partial pose. */
  readonly action: SceneAction;
  readonly environment: SceneEnvironment;
  /** Layered-rig dimensions stay orthogonal to phase, legacy face pose, and camera action. */
  readonly outfit: SceneRigOutfit;
  readonly emotion: SceneRigEmotion;
  readonly accessory: SceneRigAccessory;
  readonly photoVisible: boolean;
  readonly photoKind: 'authored' | 'generated';
  readonly subtitle: string;
}

export function initialSceneState(): SceneState {
  return {
    phase: 'idle', expression: 'calm', action: 'camera_ready', environment: 'cafe',
    outfit: 'outfit_black_jacket', emotion: 'emotion_normal', accessory: 'accessory_camera_clip',
    photoVisible: false, photoKind: 'authored', subtitle: '窗外还在下雨。和 MIRA 打个招呼吧。',
  };
}

/** No timers, asset fetching, HTML parsing, audio, or permission decisions. */
export function reduceSceneEffect(state: SceneState, effect: EffectView): SceneState {
  switch (effect.kind) {
    case 'subtitle': return { ...state, subtitle: effect.value };
    case 'pose': {
      // The app's generated wire contract remains the single source of enum values.
      // String narrowing here lets this captured renderer consume the separately
      // integrated known pose vocabulary without hand-editing generated contracts.
      const value = String(effect.value);
      switch (value) {
        case 'outfit_black_jacket': return { ...state, outfit: value };
        case 'outfit_cream_inner_only': return { ...state, outfit: value };
        case 'outfit_amber_raincoat': return { ...state, outfit: value };
        case 'emotion_normal': return { ...state, emotion: value };
        case 'emotion_guarded': return { ...state, emotion: value };
        case 'emotion_happy': return { ...state, emotion: value };
        case 'emotion_shy': return { ...state, emotion: value };
        case 'accessory_camera_clip': return { ...state, accessory: value };
        case 'accessory_star_clip': return { ...state, accessory: value };
        case 'camera_lowered': return { ...state, action: 'camera_lowered', expression: 'warm' };
        case 'camera_raise': return { ...state, action: 'camera_raise', expression: 'calm' };
        case 'camera_ready': return { ...state, action: 'camera_ready', expression: 'calm' };
        case 'look_at_rain': return { ...state, action: 'look_at_rain', expression: 'reflective' };
        case 'face_calm': return { ...state, expression: 'calm' };
        case 'face_warm': return { ...state, expression: 'warm' };
        case 'face_curious': return { ...state, expression: 'curious' };
        case 'face_reflective': return { ...state, expression: 'reflective' };
      }
      break;
    }
    case 'scene':
      switch (effect.value) {
        case 'rain_window': return { ...state, environment: 'rain_window' };
        case 'cafe': return { ...state, environment: 'cafe', action: 'camera_ready', expression: 'calm' };
        case 'cafe_warm': return { ...state, environment: 'cafe_warm', expression: 'warm' };
      }
      break;
    case 'media':
      // The legacy fixture identity now has an original local illustration, never an external URL.
      if (effect.value === 'trip_photo_placeholder' || effect.value === 'trip_photo') {
        return { ...state, photoVisible: true, photoKind: 'authored', expression: 'warm' };
      }
      if (generatedPhotoIdentity(effect.value)) return {...state, photoVisible: true, photoKind: 'generated'};
      break;
  }
  throw new Error(`Unsupported scene ${effect.kind} effect`);
}
