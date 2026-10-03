import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const source=await readFile(new URL('../../apps/web/public/audio/capture-worklet.js',import.meta.url),'utf8');
function fixture(options={}) {
  let Processor;const messages=[];
  const realm={AudioWorkletProcessor:class{constructor(){this.port={onmessage:null,postMessage:(message,transfer)=>messages.push({message,transfer})};}},
    Float32Array,Set,Math,Number,sampleRate:48000,currentFrame:0,registerProcessor:(name,ctor)=>{assert.equal(name,'mira-pcm-capture');Processor=ctor;}};
  vm.runInNewContext(source,realm,{filename:'capture-worklet.js'});
  const processor=new Processor({processorOptions:{chunkFrames:256,maxPendingChunks:2,...options}});
  const process=(channels=[new Float32Array(128).fill(1)])=>{const output=new Float32Array(128).fill(9);const keep=processor.process([channels],[[output]]);realm.currentFrame+=128;return {keep,output};};
  return {processor,messages,process};
}
test('worklet emits bounded mono frames with actual rate and never plays microphone to output',()=>{
  const f=fixture();const first=f.process([new Float32Array(128).fill(1),new Float32Array(128).fill(-1)]);
  assert.ok(first.output.every(x=>x===0));assert.equal(f.messages.length,0);f.process([new Float32Array(128).fill(1),new Float32Array(128).fill(-1)]);
  assert.equal(f.messages.length,1);const {message,transfer}=f.messages[0];assert.equal(message.sampleRate,48000);assert.equal(message.startFrame,0);assert.equal(message.sequence,0);
  assert.equal(message.samples.length,256);assert.ok(message.samples.every(x=>x===0));assert.equal(transfer[0],message.samples.buffer);
});
test('worklet blocks unlimited bridge buffering and reports overflow without silently dropping speech',()=>{
  const f=fixture();for(let i=0;i<5;i++)f.process();const result=f.process();
  assert.equal(result.keep,false);assert.equal(f.messages.filter(x=>x.message.type==='samples').length,2);
  assert.equal(f.messages.at(-1).message.type,'overflow');assert.equal(f.process().keep,false);
});
test('worklet only returns credits for known acknowledgements',()=>{
  const f=fixture();for(let i=0;i<4;i++)f.process();f.processor.port.onmessage({data:{type:'ack',sequence:999}});
  f.processor.port.onmessage({data:{type:'ack',sequence:0}});f.processor.port.onmessage({data:{type:'ack',sequence:0}});
  f.process();assert.equal(f.process().keep,true);f.process();assert.equal(f.process().keep,false);
  assert.equal(f.messages.filter(x=>x.message.type==='samples').length,3);
});
test('worklet stop drops partial frames and later messages cannot restart it',()=>{
  const f=fixture();f.process();f.processor.port.onmessage({data:{type:'stop'}});f.processor.port.onmessage({data:{type:'ack',sequence:0}});
  assert.equal(f.process().keep,false);assert.equal(f.messages.length,0);
});
test('worklet rejects invalid resource bounds',()=>{
  assert.throws(()=>fixture({maxPendingChunks:999}));assert.throws(()=>fixture({chunkFrames:999999}));
});
