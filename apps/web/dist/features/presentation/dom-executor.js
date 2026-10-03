/** Instant diagnostic DOM effects, NOT a production avatar/audio executor. */
export class DomEffectExecutor {
    root;
    constructor(root) {
        this.root = root;
    }
    element(name) {
        const target = this.root.querySelector(`[data-${name}]`);
        if (!target)
            throw new Error(`Missing stage slot: ${name}`);
        return target;
    }
    apply(effect) {
        switch (effect.kind) {
            case 'subtitle':
                this.element('subtitle').textContent = effect.value;
                return;
            case 'pose':
                this.element('pose').textContent = '相机已放低 · 占位姿态';
                return;
            case 'scene':
                this.root.dataset.scene = effect.value;
                this.element('scene-label').textContent = '雨窗视角 · 环境占位';
                return;
            case 'media':
                this.element('photo').hidden = false;
                return;
        }
    }
    prepareInput() {
        this.element('subtitle').textContent = '';
    }
    stop() {
        this.element('subtitle').textContent = '已在本地停止。已有画面保留，旧回应不会继续。';
    }
}
//# sourceMappingURL=dom-executor.js.map