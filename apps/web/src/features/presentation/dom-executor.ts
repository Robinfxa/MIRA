import type { EffectView } from '../../shared/generated/contracts.js';
import type { EffectExecutor } from './ports.js';

/** Instant diagnostic DOM effects, NOT a production avatar/audio executor. */
export class DomEffectExecutor implements EffectExecutor {
  constructor(private readonly root: HTMLElement) {}
  private element(name: string): HTMLElement {
    const target = this.root.querySelector<HTMLElement>(`[data-${name}]`);
    if (!target) throw new Error(`Missing stage slot: ${name}`);
    return target;
  }
  apply(effect: EffectView): void {
    switch (effect.kind) {
      case 'subtitle': this.element('subtitle').textContent = effect.value; return;
      case 'pose': this.element('pose').textContent = '相机已放低 · 占位姿态'; return;
      case 'scene': this.root.dataset.scene = effect.value; this.element('scene-label').textContent = '雨窗视角 · 环境占位'; return;
      case 'media': this.element('photo').hidden = false; return;
    }
  }
  prepareInput(): void {
    this.element('subtitle').textContent = '';
  }
  stop(): void {
    this.element('subtitle').textContent = '已在本地停止。已有画面保留，旧回应不会继续。';
  }
}
