/* MIRA long left waves — isolated code-native review candidate.
 * Pure modifier: call apply(composedScene, pose) before the expression modifier.
 * No image assets, raster sampling, tracing, networking, or timers.
 * Existing face, eyes, lips, neck, hands, camera and outfit paths are preserved.
 */
(function(root){
'use strict';
const VERSION='hair-flow-03-broad-silhouette';
const clamp=(v,a,b)=>Math.max(a,Math.min(b,Number.isFinite(v)?v:0));
const copy=n=>({...n,...(n.children?{children:n.children.map(copy)}:{})});
const P={dark:'#38231f',deep:'#4b2b24',base:'#704032',mid:'#92533c',light:'#bc7951',gold:'#e6ae72',cool:'#947784'};
const S=(id,d,c)=>({id,type:'path',d,fill:P[c]||c});
const G=(id,children,extra={})=>({id,type:'group',children,...extra});
function find(nodes,id){for(const n of nodes){if(n.id===id)return n;if(n.children){const hit=find(n.children,id);if(hit)return hit;}}return null;}
const topology=Object.freeze({
 version:VERSION,
 attachment:'part > left-primary > left-junction (72,108) > flowing-left-root > flowing-left-middle > flowing-left-tip',
 nodes:[
  {id:'part',parent:null,anchor:[103,31],renderIds:['crown-left','crown-right']},
  {id:'left-primary',parent:'part',anchor:[74,61],renderIds:['face-frame-left','root-to-side-main','root-to-side-body']},
  {id:'left-junction',parent:'left-primary',anchor:[72,108],renderIds:['left-front-branch-junction','branch-overlap-shadow']},
  {id:'right-primary',parent:'part',anchor:[130,48],renderIds:['crown-right','right-face-fringe','right-volume']},
  {id:'right-back-middle',parent:'right-primary',anchor:[163,103],renderIds:['right-middle-wave','right-rim']},
  {id:'flowing-left-root',parent:'left-junction',anchor:[72,108],renderIds:['flowing-left-root','flowing-left-upper-outline']},
  {id:'flowing-left-middle',parent:'flowing-left-root',anchor:[36,163],renderIds:['flowing-left-middle','flowing-left-middle-outline']},
  {id:'flowing-left-tip',parent:'flowing-left-middle',anchor:[21,235],renderIds:['flowing-left-tip','flowing-left-tip-outline']},
  {id:'flowing-inner-root',parent:'left-junction',anchor:[72,108],renderIds:['flowing-inner-root']},
  {id:'flowing-inner-tip',parent:'flowing-inner-root',anchor:[62,183],renderIds:['flowing-inner-tip']},
  {id:'flowing-right-back',parent:'right-back-middle',anchor:[163,103],renderIds:['flowing-right-back']}
 ],
 limits:{rootDegrees:.75,middleDegrees:1.60,tipDegrees:2.30,innerTipDegrees:1.15,rightTipDegrees:.80},
 occlusion:['Rear extension is behind the body.','Long left waves are over shoulder cloth but under forearms, camera and hands.','Frozen head/face and neck-framing curl remain above the shoulder waves.'],
 supportedMotion:'This layer supplies paired roll and delayed strand rotation. The composed character adds limited relative yaw projection after expression; no profile, 360-degree or physics claim.'
});
function waves(s={}){
 const active=s.running!==false&&!s.reducedMotion;
 const a=active?clamp(s.strand,-1.05,1.05)/1.05:0;
 const b=active?clamp(s.strand2,-1.5,1.5)/1.5:0;
 const c=active?clamp(s.strand3,-1.85,1.85)/1.85:0;
 const tip=G('flowing-left-tip',[
  S('flowing-left-tip-outline','M17 222 Q36 229 32 243 Q29 254 17 266 Q5 278 9 287 Q13 295 28 288 Q22 303 7 300 Q-7 299 -7 285 Q-9 273 2 262 Q-7 258 -5 248 Q-3 235 17 222Z','dark'),
  S('flowing-left-tip-body','M18 227 Q29 232 27 242 Q24 254 12 266 Q0 278 4 287 Q7 295 19 292 Q7 298 0 291 Q-7 279 5 265 Q11 258 15 251 Q2 256 1 249 Q2 238 18 227Z','base'),
  S('flowing-left-tip-shade','M26 234 Q30 245 17 257 Q0 276 5 287 Q8 292 17 291 L12 296 Q-1 296 -2 286 Q-5 275 8 262 Q25 246 26 234Z','deep'),
  S('flowing-left-tip-ribbon','M17 229 Q2 240 1 248 Q0 253 6 253 Q17 252 23 242 Q20 252 9 263 Q-6 278 -2 289 Q-10 283 -3 270 Q1 261 8 258 Q-10 259 -4 245 Q0 234 17 229Z','light'),
  S('flowing-left-tip-glint','M12 233 Q0 243 0 249 L2 252 -2 252 Q-6 245 7 235Z M4 268 Q-1 277 -1 282 L-3 285 Q-5 277 4 268Z','gold'),
  S('flowing-left-tip-split','M24 246 Q24 260 13 271 Q7 282 12 287 L18 285 Q10 294 8 287 Q3 278 16 265 Q22 256 24 246Z','mid'),
 S('flowing-tip-inner-turn','M21 230 Q18 240 10 246 L5 249 6 252 11 251 9 254 3 254 1 251 3 246 13 239Z','#a26847'),
 S('flowing-tip-recess','M25 241 Q19 255 10 264 L3 273 0 281 2 287 5 289 4 292 0 290 -2 285 -2 278 3 268 12 258Z','#3e251f'),
 S('flowing-tip-copper-plane','M14 260 Q0 275 2 284 L5 290 9 292 5 293 0 289 -2 283 0 274 6 266Z','#b8754b'),
 S('flowing-tip-taper-glint','M7 269 L3 278 3 284 5 288 3 286 1 281 3 274Z','#e0a671'),
 ],{transform:`rotate(${c*2.3} 21 235)`,pivot:[21,235],attachment:'flowing-left-middle'});
 const middle=G('flowing-left-middle',[
  S('flowing-left-middle-outline','M37 148Q63 160 56 179Q47.067 197 23.633 208Q10.4 217 18 225Q30.34 224 36.573 217Q43.36 233 30 248Q19 261 1 258Q-10 254 -7.4 243Q-8.2 229 1.6 218Q-13.8 216 -11 201Q-8 189 7 178Q-8 176 0.625 163Q10.833 152 37 148Z','dark'),
  S('flowing-left-middle-body','M37.183 154Q55 163 49.533 176Q40.9 192 18.7 205Q4 215 11.2 226Q14.6 233 27.213 226Q31.987 237 24 246Q14 257 4 253Q-4 249 0.8 239Q5.6 228 14 220Q1.6 228 -3.4 218Q-10 207 2 194Q10 185 17.467 179Q1 177 5.458 167Q14.375 157 37.183 154Z','base'),
  S('flowing-left-middle-shadow','M43.222 158Q52 166 45.833 178Q38.433 190 22.4 200Q8 210 9.6 218Q12.2 226 19.707 222L24.86 218Q35.2 227 27.04 239Q15 254 4 250Q21 248 22.133 235Q8.8 244 3.6 228Q-4.8 216 8 201Q39.667 177 43.222 158Z','deep'),
  S('flowing-left-middle-sweep','M34.911 155Q12.75 166 4 178Q0 185 9 184Q21.167 182 37.433 170Q32.267 184 14 193Q-6 207 -3.6 217Q-7.2 219 -9.8 211Q-12 197 8 183Q-6 186 -3 173Q4.5 160 34.911 155Z','light'),
  S('flowing-left-middle-gold','M26.764 158Q7.458 167 2 176Q-1 182 3 183L1 185Q-7 186 -3 176Q3.333 164 26.764 158Z','gold'),
  S('flowing-left-middle-lower-light','M17.467 199Q2 215 8 225Q13.4 237 26.7 230Q22.42 242 11 245L3.8 244Q14 235 17.2 231Q5.2 236 1.8 224Q-2.6 212 17.467 199Z','mid'),
  S('flowing-left-middle-lower-ribbon','M7.2 211Q-6.4 228 -3.2 239Q-2 250 11 250L18 248Q7 257 0 252Q-8 248 -6.6 237Q-7.4 223 7.2 211Z','light'),
  S('flowing-left-middle-lower-glint','M0.8 224Q-4.6 237 -1.4 243L-3 245Q-8.8 236 0.8 224Z','gold'),
 S('flowing-middle-deep-channel','M38.717 159Q27.333 172 13 179L7 181 7 183 16.233 182 12 186 5 187 2 184 3 179 11 174 23.333 168Z','#4d2d23'),
 S('flowing-middle-copper-facet','M37.61 159Q21.896 169 11 175L7 178 10 178 17.467 174 30.5 168 35.822 164Z','#cb8a59'),
 S('flowing-middle-fine-crest','M24.967 161L17.333 164 10.167 168 5 173 3 176 1 177 2 173 8.458 167 15.333 164Z','#edba80'),
 S('flowing-middle-descending-band','M39.667 179Q29.8 192 17.467 198L8 205 5.4 212 7.4 217 9.8 219 9.6 223 6 220 3.6 213 6 206 13 200 24.867 191Z','#aa6a47'),
 S('flowing-middle-descending-fine','M29.8 189L18.7 198 10 205 8 210 9.8 214 7.8 214 7 209 10 203 18.7 196Z','#d08b5a'),
 S('flowing-middle-inner-seam','M45.833 173Q39.667 190 23.633 202L16.233 209 15 215 17.78 218 19.96 217 21.667 220 17.4 222 13.6 218 13.2 211 18.7 204 33.5 191Z','#39231e'),
 S('flowing-middle-bottom-copper','M3 220Q-1.8 231 -0.2 239Q1 247 8 249L13 249 9 252 3 249 -1.4 243 -2.4 233Z','#ca8b5d'),
 S('flowing-middle-bottom-dark-return','M7.4 242Q16 240 22.133 235L22.033 240 16 246 8 248 4 246Z','#4a2a21'),
  tip
 ],{transform:`rotate(${b*1.6} 36 163)`,pivot:[36,163],attachment:'flowing-left-root'});
 const outer=G('flowing-left-root',[
  S('flowing-left-upper-outline','M69 93 Q73 115 62 131 Q49 147 27 151 Q10 153 8 163 Q8 171 18 175 Q32 180 46 164 Q43 181 26 187 Q8 194 -3 181 Q-15 171 -12 158 Q-11 144 10 137 Q37 132 50 119 Q59 109 61 99Z','dark'),
  S('flowing-left-upper-body','M65 99 Q68 119 56 132 Q43 144 25 147 Q6 150 2 161 Q-1 171 10 177 Q23 186 37 175 L32 181 Q18 190 7 183 Q-7 178 -8 165 Q-11 153 5 145 Q15 140 30 137 Q52 129 59 112Z','base'),
  S('flowing-left-upper-shadow','M64 106 Q59 130 40 139 Q16 147 10 154 Q1 164 11 173 Q21 182 34 174 L30 179 Q17 188 4 178 Q-8 168 -1 157 Q5 147 24 142 Q50 135 64 106Z','deep'),
  S('flowing-left-upper-ribbon','M57 116 Q43 136 19 141 Q-2 145 -7 156 Q-12 166 -4 174 L1 177 -3 176 Q-15 171 -11 157 Q-9 145 13 138 Q40 133 57 116Z','light'),
  S('flowing-left-upper-gold','M36 132 Q21 139 7 143 Q-5 147 -8 157 L-9 163 -11 161 Q-11 150 -1 144 Q11 138 26 135Z','gold'),
  S('flowing-left-upper-flow','M66 113 Q60 138 38 150 Q22 158 19 168 Q18 175 25 177 L19 177 Q10 172 15 162 Q20 154 32 148 Q55 136 66 113Z','mid'),
  S('flowing-left-upper-fine','M60 126 Q47 143 31 150 Q20 156 18 165 L18 170 15 167 Q14 157 27 150 Q48 141 60 126Z','light'),
  S('flowing-upper-inner-copper','M61 127 Q53 143 41 150 Q28 157 26 164 L24 171 22 173 21 169 23 162 Q30 154 40 149 Q52 142 61 127Z','#ad6f49'),
  S('flowing-upper-recess','M47 143 Q34 151 25 160 L21 170 23 175 21 176 17 173 18 165 23 157 35 149Z','#3e251f'),
  S('flowing-upper-ribbon-core','M18 141 L9 144 0 149 -5 155 -6 160 -8 161 -7 155 -2 148 6 144Z','#e4a876'),
  S('flowing-upper-edge-break','M-8 160 L-8 166 -5 172 -2 175 -4 175 -9 170 -10 165Z','#eac18b'),
  S('flowing-upper-fold-return','M8 176 Q22 187 35 173 L36 176 29 184 19 186 12 183 6 178Z','#a36240'),
  middle
 ],{transform:`rotate(${a*.75} 72 108)`,pivot:[72,108],attachment:'left-junction'});
 const inner=G('flowing-inner-root',[
  S('flowing-inner-outline','M70 107 Q77 127 69 145 Q84 154 78 173 Q72 187 59 195 Q70 199 67 212 Q62 230 44 242 Q32 247 28 237 Q25 225 41 212 Q51 203 49 195 Q32 194 31 181 Q30 166 44 156 Q55 147 58 136 Q57 121 70 107Z','dark'),
  S('flowing-inner-body','M69 114 Q73 130 64 145 Q77 155 72 169 Q65 184 50 190 Q40 188 38 181 Q35 171 49 159 Q61 149 63 136 Q61 123 69 114Z','base'),
  S('flowing-inner-root-shadow','M67 116 Q68 132 60 146 Q66 155 60 164 Q51 174 40 177 Q38 186 49 188 Q62 184 69 173 Q64 189 48 193 Q30 190 35 176 Q38 166 49 158 Q62 147 60 135Z','deep'),
  S('flowing-inner-root-ribbon','M66 117 Q61 137 54 147 Q50 153 41 159 Q27 170 32 181 Q33 188 42 190 L45 189 Q32 186 36 178 Q40 169 50 164 Q65 152 67 140 Q71 128 66 117Z','light'),
  S('flowing-inner-root-glint','M56 147 Q50 156 40 163 Q32 171 33 176 L31 179 Q27 170 37 161Z','gold'),
  S('flowing-inner-root-edge','M71 139 Q81 150 73 167 Q68 179 58 185 L52 187 Q65 175 68 165 Q74 151 71 139Z','mid'),
 S('flowing-inner-upper-channel','M68 125 Q65 141 59 148 L51 156 42 163 39 170 40 175 43 177 41 179 38 176 36 170 39 163 51 153 59 143Z','#4a2c23'),
 S('flowing-inner-crest-copper','M63 136 Q60 149 51 158 L43 165 40 172 38 174 38 170 41 163 51 154 57 146Z','#bd7d51'),
 S('flowing-inner-reflected-edge','M68 148 Q75 159 67 172 L61 179 56 182 62 175 65 168 67 158Z','#9c5c3e'),
 S('flowing-inner-crest-glint','M46 161 L39 168 36 174 36 178 34 177 34 172 40 165Z','#edbb83'),
  G('flowing-inner-tip',[
   S('flowing-inner-tip-outline','M60 181 Q75 195 66 210 Q58 221 45 225 Q39 229 43 233 Q49 238 58 230 Q53 246 39 249 Q26 248 25 237 Q22 224 39 213 Q55 203 51 192Z','dark'),
   S('flowing-inner-tip-body','M60 185 Q69 196 61 208 Q53 219 42 222 Q31 228 34 236 Q37 243 48 237 Q39 247 32 241 Q25 232 35 221 Q45 211 53 206 Q58 197 55 191Z','base'),
   S('flowing-inner-tip-shadow','M63 193 Q65 208 47 219 Q31 228 35 235 Q37 241 45 237 L39 243 Q28 242 29 233 Q29 222 43 213 Q58 204 59 196Z','deep'),
   S('flowing-inner-tip-ribbon','M58 187 Q61 199 52 208 Q45 215 35 221 Q23 231 29 241 Q36 251 50 240 Q43 250 34 249 Q23 246 23 237 Q22 223 40 212 Q56 203 54 190Z','light'),
   S('flowing-inner-tip-glint','M39 216 Q26 226 26 232 L25 235 Q23 226 35 219Z','gold'),
 S('flowing-inner-tip-channel','M60 190 Q60 205 47 214 L39 220 33 227 32 234 36 239 33 239 30 235 30 228 35 220 44 212 55 202Z','#492a21'),
 S('flowing-inner-tip-copper','M58 193 Q57 205 44 214 L36 221 30 229 30 235 28 236 28 229 32 222 41 214 52 205Z','#cc8e61'),
 S('flowing-inner-tip-crest-fine','M43 215 L36 221 31 228 30 231 29 230 30 225 35 220Z','#e2b07e'),
 S('flowing-inner-tip-return','M34 240 Q40 245 48 237 L47 240 40 245 36 244 32 242Z','#a06142'),
  ],{transform:`rotate(${c*1.15} 62 183)`,pivot:[62,183],attachment:'flowing-inner-root'})
 ],{transform:`rotate(${a*.45} 72 108)`,pivot:[72,108],attachment:'left-junction'});
 return [outer,inner];
}
function rightBack(s={}){
 const v=s.running!==false&&!s.reducedMotion?clamp(s.strand3,-1.85,1.85)/1.85:0;
 return G('flowing-right-back',[
  S('flowing-right-back-outline','M157 115 Q169 138 187 146 Q210 153 213 171 Q218 184 204 191 Q222 203 215 220 Q210 235 192 239 L188 224 Q201 221 199 212 Q181 202 174 193 Q164 173 159 153Z','dark'),
  S('flowing-right-back-body','M164 124 Q174 142 190 151 Q209 158 208 171 Q211 183 198 188 Q215 201 209 218 Q206 228 196 230 L194 223 Q206 217 201 208 Q183 198 180 188 Q169 167 164 147Z','base'),
  S('flowing-right-back-shadow','M171 143 Q177 158 193 167 Q201 177 191 183 Q200 195 207 202 L206 213 Q201 201 184 193 Q174 180 171 164Z','deep'),
  S('flowing-right-back-rim','M177 142 Q191 152 202 160 Q214 169 207 180 L204 184 199 184 Q209 174 201 166 Q186 157 177 147Z M199 191 Q219 202 211 218 L205 224 207 215 Q209 203 199 196Z','cool'),
  S('flowing-right-back-ribbon','M171 154 Q178 172 191 179 L196 182 191 183 Q178 178 171 164Z','light'),
 S('flowing-right-copper-channel','M176 149 Q179 160 190 168 L196 174 197 178 194 181 191 181 194 178 193 173 185 168 179 161Z','#9e6249'),
 S('flowing-right-rim-fine','M189 152 L199 159 205 165 207 172 205 177 203 179 205 173 203 167 198 162Z','#b497a1'),
 S('flowing-right-lower-channel','M194 193 Q207 202 204 211 L200 217 197 219 197 216 201 212 202 207 199 201Z','#482821'),
 ],{transform:`rotate(${v*.8} 163 103)`,pivot:[163,103],attachment:'right-back-middle'});
}
function apply(scene,pose={}){
 if(!scene||!Array.isArray(scene.layers)||scene.width!==288||scene.height!==408)throw new Error('Hair modifier requires a 288 × 408 semantic scene');
 const result={...scene,layers:scene.layers.map(copy)};
 if(find(result.layers,'flowing-left-root'))throw new Error('Hair modifier must be applied exactly once');
 const layout=find(result.layers,'composition-layout');
 const head=find(result.layers,'head-rig'),rear=find(result.layers,'rear-hair-rig'),neck=find(result.layers,'neck-rig');
 const body=find(result.layers,'body-rig');
 if(!layout||layout.transform!=='translate(18 0)'||!head||!rear||!neck||!body)throw new Error('Hair modifier requires the 288 × 408 proportional composition');
 if(head.transform!==rear.transform||head.transform!==neck.transform)throw new Error('Hair anatomy transforms must remain paired');
 if(!find(result.layers,'left-front-branch-junction')||!find(result.layers,'right-middle-wave'))throw new Error('Hair root contract changed');
 const index=body.children.findIndex(n=>n.id==='elbows-and-forearms');
 if(index<0)throw new Error('Body forearm occlusion seam changed');
 const backHair=find(result.layers,'hair-back');
 backHair.children.push(rightBack(pose));
 const interaction={...body,id:'body-interaction-over-hair',children:body.children.slice(index)};
 body.children=body.children.slice(0,index);
 // Replace the old short articulated branch with these long descendants.
 // Its shared left-junction/root stays intact; all non-hair geometry is kept.
 const shortLockIndex=head.children.findIndex(n=>n.id==='articulated-lock-root');
 if(shortLockIndex<0)throw new Error('Existing left lock contract changed');
 head.children.splice(shortLockIndex,1);
 const registration=head.staticRegistration||{x:0,y:0};
 const front=G('flowing-shoulder-hair-rig',waves(pose),{transform:head.transform+` translate(${registration.x} ${registration.y})`,pivot:[72,108],attachment:'head-rig/left-front-branch-junction'});
 const bodyIndex=layout.children.indexOf(body);
 if(bodyIndex<0)throw new Error('Body must be a direct composition child');
 layout.children.splice(bodyIndex+1,0,front,interaction);
 result.hairRefinement={version:VERSION,topology};
 return result;
}
const API={VERSION,topology,apply};
if(typeof module!=='undefined'&&module.exports)module.exports=API;
root.MiraHairRefinement=API;
})(typeof window!=='undefined'?window:globalThis);
