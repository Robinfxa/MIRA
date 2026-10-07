import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const dist=pathToFileURL(resolve(process.env.MIRA_TEST_WEB_DIST??'apps/web/dist')+'/').href;
const {LocalBargeInDetector}=await import(new URL('features/audio/local-barge-in.js',dist));
function harness(mode='headphones') {
  const detector=new LocalBargeInDetector(mode);let sequence=0,sample=0;
  return {detector,push(amplitude,{milliseconds=40,playbackBusy=true,noiseFloor=40,...overrides}={}) {
    const count=milliseconds*16,pcm=new Int16Array(count).fill(amplitude);
    const chunk={pcm16le:new Uint8Array(pcm.buffer),sampleRate:16000,channels:1,sequence:sequence++,startSample:sample,endSample:sample+=count,...overrides};
    return detector.observe(chunk,{playbackBusy,noiseFloor});
  }};
}
test('explicit headphones qualifies only after 160 ms with an exact current range',()=>{
  const h=harness();for(let i=0;i<3;i++)assert.equal(h.push(1800).kind,'candidate');
  assert.deepEqual(h.push(1800),{kind:'qualified',startSample:0,endSample:2560});
  for(let i=0;i<20;i++)assert.equal(h.push(1800).kind,'none','one onset cannot repeat');
});
test('guarded default never qualifies speaker-like overlap or creates pending candidates',()=>{
  const h=harness('guarded');for(let i=0;i<100;i++)assert.equal(h.push(1800).kind,'none');
  const defaultDetector=new LocalBargeInDetector();assert.equal(defaultDetector.mode,'guarded');
});
test('quiet and 120 ms noise never qualify; an interrupted candidate cannot donate old samples',()=>{
  const h=harness();for(let i=0;i<30;i++)assert.equal(h.push(120).kind,'none');
  for(let i=0;i<3;i++)assert.equal(h.push(1800).kind,'candidate');
  assert.equal(h.push(0).kind,'none');for(let i=0;i<3;i++)assert.equal(h.push(1800).kind,'candidate');
  assert.deepEqual(h.push(1800),{kind:'qualified',startSample:21760,endSample:24320});
});
test('200 ms quiet rearms and incomplete quiet does not',()=>{
  const h=harness();for(let i=0;i<4;i++)h.push(1800);
  for(let i=0;i<4;i++)h.push(0);for(let i=0;i<4;i++)assert.equal(h.push(1800).kind,'none');
  for(let i=0;i<5;i++)h.push(0);for(let i=0;i<3;i++)h.push(1800);
  assert.equal(h.push(1800).kind,'qualified');
});
test('idle PCM does not qualify or carry an energetic onset into new playback',()=>{
  const h=harness();for(let i=0;i<20;i++)assert.equal(h.push(1800,{playbackBusy:false}).kind,'none');
  for(let i=0;i<3;i++)assert.equal(h.push(1800).kind,'candidate');assert.equal(h.push(1800).kind,'qualified');
});
test('sample duration drives qualification across supported chunk sizes',()=>{
  for(const milliseconds of [10,20,40,80]) {const h=harness();for(let i=0;i<160/milliseconds-1;i++)assert.equal(h.push(1800,{milliseconds}).kind,'candidate');
    assert.equal(h.push(1800,{milliseconds}).kind,'qualified');}
});
test('bounded ambient threshold rejects raised low noise while admitting stronger local sound',()=>{
  const h=harness();for(let i=0;i<30;i++)assert.equal(h.push(1000,{noiseFloor:300}).kind,'none');
  for(let i=0;i<3;i++)h.push(1600,{noiseFloor:300});assert.equal(h.push(1600,{noiseFloor:300}).kind,'qualified');
});
test('duplicate, gap, rollback, malformed and stale delivery latch invalid until reset',()=>{
  for(const overrides of [{sequence:0},{sequence:3},{startSample:0},{endSample:1000},{sampleRate:24000},
    {channels:2},{pcm16le:new Uint8Array(3)},{deliveryLagMilliseconds:201},{deliveryLagMilliseconds:NaN}]) {
    const h=harness();h.push(1800);assert.equal(h.push(1800,overrides).kind,'invalid');
    for(let i=0;i<8;i++)assert.equal(h.push(1800).kind,'invalid');h.detector.reset();
    const pcm=new Uint8Array(new Int16Array(640).fill(1800).buffer);
    assert.equal(h.detector.observe({pcm16le:pcm,sampleRate:16000,channels:1,sequence:0,startSample:0,endSample:640},
      {playbackBusy:true,noiseFloor:40}).kind,'candidate');
  }
});
test('lease reset discards prior latch, range and sequence without retaining any audio',()=>{
  const h=harness();for(let i=0;i<4;i++)h.push(1800);h.detector.reset();
  const pcm=new Uint8Array(new Int16Array(640).fill(1800).buffer);
  for(let i=0;i<4;i++) {const result=h.detector.observe({pcm16le:pcm,sampleRate:16000,channels:1,sequence:i,startSample:i*640,endSample:(i+1)*640},
    {playbackBusy:true,noiseFloor:40});if(i===3)assert.equal(result.kind,'qualified');}
  assert.ok(Object.values(h.detector).every(value=>!(value instanceof ArrayBuffer)&&!ArrayBuffer.isView(value)));
});
test('identical microphone observations cannot prove speaker echo differs from user speech',()=>{
  const user=harness(),echo=harness();for(let i=0;i<4;i++)assert.deepEqual(user.push(1800),echo.push(1800));
});
