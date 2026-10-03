/** Stateful box-filter resampler. Input rates are real AudioContext rates, never guessed. */
export class StreamingPcm16Resampler {
    inputRate;
    filled = 0;
    sum = 0;
    constructor(inputRate) {
        this.inputRate = inputRate;
        if (!Number.isSafeInteger(inputRate) || inputRate < 8_000 || inputRate > 192_000)
            throw new RangeError('Unsupported capture sample rate');
    }
    push(input) {
        if (!(input instanceof Float32Array) || !input.every(Number.isFinite))
            throw new TypeError('Invalid capture samples');
        // Integer rate units prevent fractional frame drift at 44.1 kHz across callbacks.
        const frames = Math.floor((this.filled + input.length * 16_000) / this.inputRate);
        const output = new Uint8Array(frames * 2);
        const view = new DataView(output.buffer);
        let offset = 0;
        for (const value of input) {
            let remaining = 16_000;
            const sample = Math.max(-1, Math.min(1, value));
            while (remaining > 0) {
                const width = Math.min(remaining, this.inputRate - this.filled);
                this.sum += sample * width;
                this.filled += width;
                remaining -= width;
                if (this.filled === this.inputRate) {
                    const normalized = this.sum / this.inputRate;
                    const pcm = normalized < 0 ? Math.round(normalized * 32768) : Math.round(normalized * 32767);
                    view.setInt16(offset, pcm, true);
                    offset += 2;
                    this.filled = 0;
                    this.sum = 0;
                }
            }
        }
        return output;
    }
}
//# sourceMappingURL=pcm.js.map