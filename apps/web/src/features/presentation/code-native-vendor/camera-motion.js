/* Bounded 2.5D camera lift. Pure path deformation of authored limb segments.
 * Camera, fingers and watch remain one rigid assembly. Shoulders stay anchored;
 * projected elbow and wrist chains describe depth foreshortening, not full 3D IK.
 * Native travel: 81 px up / 9 px right. Final pose is upper chest, below the eye.
 */
(function(root){
'use strict';
const clamp=v=>Math.max(0,Math.min(1,Number.isFinite(v)?v:0));
const mix=(a,b,t)=>a.map((v,i)=>v+(b[i]-v)*t);
const round=v=>+v.toFixed(5);
function rig(progress,breathing={}){
 const t=clamp(progress),delta=[6*t,-54*t];
 const b=Number.isFinite(breathing.breath)?Math.max(-1,Math.min(1,breathing.breath)):0;
 const lag=Number.isFinite(breathing.armBreath)?Math.max(-1,Math.min(1,breathing.armBreath)):0;
 const shoulder=([x,y])=>[110+(x-110)*(1+b*.006),285+(y-285)*(1+b*.007)];
 const elbow=([x,y])=>[x+(x-110)*lag*.003,y-lag*.45];
 return {progress:t,delta,
  left:{shoulder:shoulder([40,178]),elbow:elbow(mix([31,280],[23,267],t)),wrist:[70+delta[0],279+delta[1]]},
  right:{shoulder:shoulder([157,179]),elbow:elbow(mix([169,286],[178,275],t)),wrist:[150+delta[0],296+delta[1]]}};
}
function segment(a,b,c,d){
 const u=[b[0]-a[0],b[1]-a[1]],v=[d[0]-c[0],d[1]-c[1]];
 const length=Math.hypot(...u),next=Math.hypot(...v);
 return (x,y)=>{const along=((x-a[0])*u[0]+(y-a[1])*u[1])/(length*length);
  const across=(-(x-a[0])*u[1]+(y-a[1])*u[0])/length;
  return [c[0]+along*v[0]-across*v[1]/next,c[1]+along*v[1]+across*v[0]/next];};
}
// Authored sources use absolute M/L/Q/C coordinates, with no arc/radius tokens.
function path(d,map){return d.replace(/([+-]?(?:\d*\.)?\d+(?:e[+-]?\d+)?)\s+([+-]?(?:\d*\.)?\d+(?:e[+-]?\d+)?)/gi,(_,x,y)=>map(+x,+y).map(round).join(' '));}
function deform(node,map){return {...node,...(node.d?{d:path(node.d,map)}:{}),...(node.clip?{clip:path(node.clip,map)}:{}),...(node.pivot?{pivot:map(...node.pivot)}:{}),...(node.children?{children:node.children.map(n=>deform(n,map))}:{})};}
function apply(parts,progress,breathing={}){
 const r=rig(progress,breathing),t=r.progress;if(t===0&&!breathing.breath&&!breathing.armBreath)return parts;
 const leftUpper=segment([40,178],[31,280],r.left.shoulder,r.left.elbow);
 const rightUpper=segment([157,179],[169,286],r.right.shoulder,r.right.elbow);
 const leftFore=segment([31,280],[70,279],r.left.elbow,r.left.wrist);
 const rightFore=segment([169,286],[150,296],r.right.elbow,r.right.wrist);
 const upper=(node,map)=>({...deform(node,map),transform:undefined});
 const limb=(node,map,fore)=>({...node,children:node.children.map(n=>n.id.startsWith('forearm-')?deform(n,fore):deform(n,map))});
 const translate=`translate(${round(r.delta[0])} ${round(8+r.delta[1])})`;
 const straps=deform(parts.straps,(x,y)=>{
  // Shoulder end fixed. Flexible hanging portion takes up slack toward the lugs.
  const w=clamp((y-196)/72),ease=w*w*(3-2*w);
  const b=Number.isFinite(breathing.breath)?breathing.breath:0;
  return [x+r.delta[0]*ease+(x-110)*b*.006*(1-ease),y+r.delta[1]*ease+(y-285)*b*.007*(1-ease)];
 });
 return {...parts,leftUpper:upper(parts.leftUpper,leftUpper),rightUpper:upper(parts.rightUpper,rightUpper),straps,
  forearms:{...parts.forearms,children:parts.forearms.children.map(n=>n.id==='elbow-left'?limb(n,leftUpper,leftFore):limb(n,rightUpper,rightFore))},
  camera:{...parts.camera,transform:translate},hands:{...parts.hands,transform:translate}};
}
root.MiraCameraMotion=Object.freeze({rig,apply});
})(typeof window!=='undefined'?window:globalThis);
