/* Browser audio thread only. No network, provider, permission or playback policy. */
class MiraPcmCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const {chunkFrames, maxPendingChunks} = options.processorOptions;
    if (!Number.isInteger(chunkFrames) || chunkFrames < 1 || chunkFrames > Math.ceil(sampleRate / 10)
      || !Number.isInteger(maxPendingChunks) || maxPendingChunks < 1 || maxPendingChunks > 32) {
      throw new RangeError('Invalid capture buffer bounds');
    }
    this.chunkFrames = chunkFrames;
    this.maxPendingChunks = maxPendingChunks;
    this.samples = new Float32Array(chunkFrames);
    this.offset = 0;
    this.startFrame = 0;
    this.sequence = 0;
    this.pending = new Set();
    this.stopped = false;
    this.port.onmessage = event => {
      const data = event.data;
      if (!data || this.stopped) return;
      if (data.type === 'stop') {
        this.stopped = true;
        this.samples = null;
        this.pending.clear();
      } else if (data.type === 'ack') {
        // A repeated/unknown ack must never create extra credits.
        this.pending.delete(data.sequence);
      }
    };
  }
  process(inputs, outputs) {
    // Always silence the destination graph; capture is not microphone monitoring.
    for (const output of outputs) for (const channel of output) channel.fill(0);
    if (this.stopped) return false;
    const channels = inputs[0];
    if (!channels || channels.length === 0) return true;
    const frames = channels[0].length;
    for (let index = 0; index < frames; index++) {
      if (this.offset === 0) this.startFrame = currentFrame + index;
      let mono = 0;
      for (const channel of channels) mono += channel[index] ?? 0;
      this.samples[this.offset++] = mono / channels.length;
      if (this.offset !== this.chunkFrames) continue;
      if (this.pending.size >= this.maxPendingChunks) {
        this.stopped = true;
        this.samples = null;
        this.port.postMessage({type: 'overflow'});
        return false;
      }
      const sequence = this.sequence++;
      const samples = this.samples;
      this.pending.add(sequence);
      this.port.postMessage({type: 'samples', samples, sampleRate, startFrame: this.startFrame, sequence}, [samples.buffer]);
      this.samples = new Float32Array(this.chunkFrames);
      this.offset = 0;
    }
    return true;
  }
}
registerProcessor('mira-pcm-capture', MiraPcmCapture);
