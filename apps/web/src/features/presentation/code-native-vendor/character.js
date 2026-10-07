/* MIRA — neck volume / lateral eyelid refinement 11, isolated review candidate.
   Retains the frozen crown/body; rebuilds connected eyelid, gaze, jaw and neck volumes.
   Whole-head registration retains +3 native x, with vertical placement aligned to the reference. Neck and trapezius use direct connected contours, without a coordinate deformation field.
   Semantic IDs, expression seams and body overlap preserved. Drawn clavicle geometry is corrected separately from attachment metadata.
   MIRA — hand-authored semantic geometry. No raster source, generated-image or tracing dependency.
   Coordinates: 192 × 224. Layer order and pivots are intentionally editable. */
(function(root){
'use strict';
const W=192,H=224;
const HEAD_REGISTRATION=Object.freeze({x:3,y:0});
const hairTopology={"purpose":"Editable attachment graph for the visible code-drawn bundles; display layer order remains separate from physical strand ancestry.","nodes":[{"id":"part","parent":null,"anchor":[103,31],"renderIds":["crown-left","crown-right"]},{"id":"left-primary","parent":"part","anchor":[74,61],"renderIds":["crown-left","face-frame-left","root-to-side-main","root-to-side-body"]},{"id":"left-junction","parent":"left-primary","anchor":[72,108],"renderIds":["left-front-branch-junction","branch-overlap-shadow"]},{"id":"left-curl-root","parent":"left-junction","anchor":[71,107],"renderIds":["articulated-lock-root","lock-root"]},{"id":"left-curl-middle","parent":"left-curl-root","anchor":[70,128],"renderIds":["articulated-lock-middle","lock-mid"]},{"id":"left-curl-tip","parent":"left-curl-middle","anchor":[65,150],"renderIds":["articulated-lock-tip","lock-tip"]},{"id":"neck-front-branch","parent":"left-junction","anchor":[88,129],"renderIds":["neck-framing-curl","neck-curl-outline","neck-curl-main"]},{"id":"neck-front-tip","parent":"neck-front-branch","anchor":[84,220],"renderIds":["neck-curl-lower-band","neck-curl-lower-fine"]},{"id":"right-primary","parent":"part","anchor":[130,48],"renderIds":["crown-right","right-face-fringe","right-volume"]},{"id":"right-back-middle","parent":"right-primary","anchor":[163,103],"renderIds":["right-middle-wave","right-rim"]},{"id":"right-back-tip","parent":"right-back-middle","anchor":[171,156],"renderIds":["right-bottom-wave","right-bottom-light"]}],"occlusion":["Rear mass is below neck/body.","Left primary transition is behind the face and cannot cover the eye or eyebrow.","Foreground branch and articulated curl are above the face/neck edges but start at the shared side junction."],"limitation":"An explicit rooted shape graph does not establish final visual likeness; the broad curls remain simplified."};
const palette={ink:'#211b22',hairDark:'#38231f',hairDeep:'#4b2b24',hair:'#704032',hairMid:'#92533c',hairLight:'#bc7951',hairGold:'#e6ae72',hairCool:'#947784',skinShadow:'#b56146',skinDeep:'#d57f5b',skin:'#eead83',skinLight:'#ffd0a3',skinGlow:'#ffdfb6',blush:'#e38e75',lipDark:'#813c35',lip:'#c66856',lipLight:'#ef997c',mouth:'#4a2526',white:'#fff0d2',iris:'#bf8a2c',irisLight:'#f4c965',pupil:'#241a19',jacket:'#262936',jacketLight:'#424454',jacketDeep:'#191c27',ivory:'#eee3cb',ivoryShade:'#cabcaa',gold:'#d49c3d',goldLight:'#ffe1a0',silver:'#acb7bb'};
const shape=(id,d,color,extra={})=>({id,type:'path',d,fill:palette[color]||color,...extra});
const group=(id,children,extra={})=>({id,type:'group',children,...extra});
// Deterministic local performance. Units are native canvas pixels and degrees.
// A neck-base pivot keeps the adopted chest root registered; no canvas bob.
function stateAt(mode='idle',time=0,running=true,controls={}){
 const safeTime=Number.isFinite(time)?Math.min(86400,Math.max(0,time)):0;
 mode=['idle','listen','think','speak'].includes(mode)?mode:'idle';
 const t=running?safeTime:0,active=!!running;
 const smooth=v=>{v=Math.max(0,Math.min(1,v));return v*v*(3-2*v);};
 const pulse=(time,start,duration)=>{const p=(time-start)/duration;return p>0&&p<1?Math.sin(p*Math.PI)**2:0;};
 // Irregular gaze holds and double-blinks avoid a single synchronized sine loop.
 const cycle=t%16;
 let blink=1;
 for(const at of [2.05,5.75,9.1,9.47,13.65]){
  const p=(cycle-at)/.25;
  if(p>=0&&p<1)blink=Math.min(blink,.06+.94*Math.abs(2*p-1));
 }
 const glance=(smooth((cycle-3.1)/.24)-smooth((cycle-4.6)/.35))*1.9
             -(smooth((cycle-10.6)/.25)-smooth((cycle-12.4)/.4))*1.5;
 const breathing=at=>.85*Math.sin(at*1.25)+.15*Math.sin(at*2.5);
 const breath=breathing(t),armBreath=breathing(t-.22);
 const drift=1.10*Math.sin(t*.72)+.22*Math.sin(t*1.43);
 const nod=pulse(t%5.8,1.4,1.15)-.6*pulse(t%5.8,2.65,.9);
 const yawLook=11*(smooth((cycle-1.1)/1.4)-smooth((cycle-5.3)/1.6))-11*(smooth((cycle-8.0)/1.5)-smooth((cycle-12.4)/1.5));
 const poses={
  idle:{yaw:yawLook,follow:yawLook/30,raise:0,lean:0,head:drift,gazeX:glance,gazeY:.2*Math.sin(t*.8),brow:0,eye:1,gesture:0},
  listen:{yaw:-8+.8*Math.sin(t*.52),follow:-.42,raise:.20*pulse(t%8,2.2,2.3),lean:.8,head:-2.1+.4*Math.sin(t*.8)+nod*.65,gazeX:-.55+.22*Math.sin(t*.7),gazeY:-.15,brow:.6,eye:1.04,gesture:0},
  think:{yaw:10+1.2*Math.sin(t*.45),follow:.48,raise:.42*pulse(t%9,1.5,3),lean:.15,head:2.4+.45*Math.sin(t*.65),gazeX:3.4+.35*Math.sin(t*.55),gazeY:-2.2,brow:1,eye:.91,gesture:0},
  speak:{yaw:yawLook*.6,follow:yawLook/36,raise:.6*pulse(t%5.8,1.1,2.4),lean:.12,head:.15+.65*Math.sin(t*.95)+nod*1.65,gazeX:.45*Math.sin(t*.6),gazeY:.2*Math.sin(t*.8),brow:.25+.32*nod,eye:1,gesture:.105*pulse(t%5.8,1.1,2.4)}
 };
 const weights=controls.phaseWeights||{[mode]:1};
 const p={yaw:0,follow:0,raise:0,lean:0,head:0,gazeX:0,gazeY:0,brow:0,eye:0,gesture:0};let total=0;
 for(const [key,weight] of Object.entries(weights))if(poses[key]&&Number.isFinite(weight)&&weight>0){total+=weight;for(const channel of Object.keys(p))p[channel]+=poses[key][channel]*weight;}
 if(total)for(const key of Object.keys(p))p[key]/=total;else Object.assign(p,poses[mode]);
 const lipWeights=controls.lipWeights||{[controls.emotion||'normal']:1};
 const emotionalMouth=4.4*pulse(t%6.8,.35,3.0)*(lipWeights.happy||0)+.38*pulse(t%9,.8,2.4)*(lipWeights.shy||0);
 const mouth=!active?0:mode==='speak'?(.8+(Math.sin(t*11.4)*.5+.5)*2.5)*(1+.28*(lipWeights.happy||0)-.12*(lipWeights.guarded||0))+.7*(lipWeights.happy||0):emotionalMouth;
 const smileTeeth=active?(lipWeights.happy||0)*smooth((mouth-1.2)/1.4):0;
 const emotionalHead=Object.entries({normal:0,guarded:-2.4,happy:-2.2,shy:3.3}).reduce((v,[key,bias])=>v+bias*(lipWeights[key]||0),0);
 const head=active?Math.max(-4,Math.min(4,p.head+emotionalHead)):0;
 // Bound the two authored crown crests after neck-base rotation. The head
 // has its own small displacement; the canvas, torso and pelvis do not move.
 const a=head*Math.PI/180,c=Math.cos(a),sn=Math.sin(a);
 const crestMin=(x0,y0,x1,y1,x2,y2)=>{
  const A=sn*(x0-2*x1+x2)+c*(y0-2*y1+y2),B=2*(sn*(x1-x0)+c*(y1-y0));
  const u=Math.max(0,Math.min(1,-B/(2*A)));
  const y=t=>{const x=(1-t)**2*x0+2*(1-t)*t*x1+t*t*x2+3,yy=(1-t)**2*y0+2*(1-t)*t*y1+t*t*y2;return 168.55+sn*(x-135.04)+c*(yy-168.55);};
  return Math.min(y(0),y(u),y(1));
 };
 const headY=active?Math.max(0,.55-Math.min(crestMin(77,1,87,-6,98,3),crestMin(76,1,89,-7,101,7))):0;
 return {mode,time:t,running,head,
  yaw:active?Math.max(-15,Math.min(15,Number.isFinite(controls.yaw)?controls.yaw:p.yaw)):0,
  shoulderFollow:active?p.follow:0,shoulderRaise:active?p.raise:0,listeningLean:active?p.lean:0,
  headX:0,headY,breath:active?breath:0,armBreath:active?armBreath:0,
  breathGrip:active?.013*(1+Math.sin(t*1.25-.28))/2:0,
  eyeOpen:active?blink*p.eye:1,gazeX:active?p.gazeX:0,gazeY:active?p.gazeY:0,
  brow:active?p.brow:0,gesture:active?p.gesture:0,
  // Stage demonstration only. There is deliberately no audio/PCM claim here.
  mouth,smileTeeth,
  strand:active?(Math.sin(t*.72-.35)*.78+Math.sin(t*1.25-.3)*.22)*1.05:0,
  strand2:active?(Math.sin(t*.72-.8)*.78+Math.sin(t*1.25-.6)*.22)*1.5:0,
  strand3:active?(Math.sin(t*.72-1.3)*.78+Math.sin(t*1.25-.95)*.22)*1.85:0};
}
function eye(id,x,y,angle,s){
 return group(id,[
  group(id+'-aperture',[
   shape(id+'-white','M-11 0 Q-3 -6.5 7 -3.5 L11 -1.5 Q3 4 -5 3Z','white'),
   shape(id+'-iris','M-3 -4.5 Q3 -6 5 -2 L5 1 Q3 5 -1 3 Q-5 2 -3 -4.5Z','iris',{transform:`translate(${s.gazeX} 0)`}),
   shape(id+'-iris-light','M-2 0 L0 3 3 2 4 0 3 3 0 4 -2 2Z','irisLight',{transform:`translate(${s.gazeX} 0)`}),
   shape(id+'-pupil','M0 -4 L3 -3 3 1 1 2 -1 1 -1 -3Z','pupil',{transform:`translate(${s.gazeX} 0)`}),
   shape(id+'-catchlight','M-2 -2 L0 -2 0 0 -2 0Z','white',{transform:`translate(${s.gazeX} 0)`}),
   shape(id+'-upper-lid','M-12 -1 L-9 -4 -10 -7 -7 -5 -5 -7 -4 -5 Q2 -7 7 -5 L11 -8 10 -5 14 -7 11 -2 Q5 -6 -3 -4Z','ink'),
   shape(id+'-lower-lid','M-10 1 Q0 5.5 9 0 L6 3 Q-2 6 -8 3Z','skinShadow')
  ],{transform:`scale(1 ${s.eyeOpen})`}),
  shape(id+'-lid-crease','M-10 -7 Q0 -11 9 -8 L7 -7 Q0 -9 -8 -6Z','skinDeep'),
  shape(id+'-closed-lid','M-11 0 Q0 4 11 -2 L13 -4 10 -1 Q1 5 -9 2Z','ink',{opacity:s.eyeOpen<.25?1:0})
 ],{transform:`translate(${x} ${y}) rotate(${angle})`});
}
/* Manual landmark-guided source-coordinate contours from user-selected pixel-coarse-v2; code likeness remains unapproved.
   No raster texture or automated pixel tessellation. Each path is one editable anatomical part. */
function referenceFace(s,shape,group){
 const skin='#ffc59f', light='#ffcca6', glow='#ffdbb6', shadow='#dc805f', line='#963f32';
 const sx=.29,tx=-50.56,ty=-12.99;
 const scleraL='M423 334 Q435 323 451 319 Q469 317 485 325 L490 330 Q477 336 464 341 Q443 347 423 334Z';
 const scleraR='M541 302 Q548 286 565 278 Q586 269 613 263 Q606 282 589 294 Q567 307 541 302Z';
 function eye(id,cx,cy,angle,sclera,iris,lash,lower,closed){
 // Close onto the same compressed ink contour: the old independent closed
 // curve sat several native pixels below the moving lid. Static open eyes
 // retain the exact original paths, transforms, fills and opacity attributes.
 const closeAt=.18, eyeScale=Math.max(closeAt,s.eyeOpen);
 const blinkFade=Math.min(1,Math.max(0,(s.eyeOpen-closeAt)/.25));
 const fading=blinkFade<1?{opacity:blinkFade}:{};
 const eyeTransform=`translate(${cx} ${cy}) rotate(${angle}) scale(1 ${eyeScale}) rotate(${-angle}) translate(${-cx} ${-cy})`;
 const lashTips=id==='left-eye'?'M418 331 L405 325 416 325Z M426 322 L416 310 432 318Z M440 316 L431 307 445 314Z M453 315 L451 306 460 314Z M423 337 L421 344 429 340Z M435 343 L435 349 442 345Z M448 346 L451 351 455 344Z M461 343 L466 348 468 341Z M474 338 L480 341 480 335Z':'M548 286 L540 279 552 281Z M558 278 L552 267 563 274Z M570 271 L569 260 576 268Z M581 267 L585 254 590 265Z M594 264 L602 250 602 262Z M605 261 L617 245 614 260Z M615 258 L629 242 623 258Z M617 262 L632 253 625 267 610 273Z M548 303 L546 310 554 305Z M560 307 L563 313 566 305Z M574 304 L580 310 582 301Z M589 299 L597 303 596 294Z M604 288 L611 291 610 283Z';
 return group(id,[
 group(id+'-open',[
 shape(id+'-sclera',sclera,'#fff5df',fading),
 group(id+'-iris-clip',[group(id+'-gaze',[
 shape(id+'-iris',iris,'#93652b'),
 shape(id+'-iris-shadow',id==='left-eye'?'M445 318 Q462 312 478 319 L480 326 Q462 331 447 326Z':'M561 271 Q577 264 594 270 L595 279 Q578 284 563 280Z','#71451f'),
 shape(id+'-iris-gold',id==='left-eye'?'M448 329 Q461 338 479 329 L478 336 472 341 465 342 455 339Z':'M564 285 Q579 293 594 281 L594 288 589 295 582 298 573 296 567 291Z','#d9a43e'),
 shape(id+'-iris-glow',id==='left-eye'?'M458 337 L465 339 473 335 471 341 465 342 459 340Z':'M573 291 L581 293 590 288 586 297 580 298 573 295Z','#ffdf84'),
 shape(id+'-pupil',id==='left-eye'?'M453 316 Q462 313 470 318 L472 327 Q470 333 463 333 Q457 332 454 327Z':'M571 270 Q579 267 585 272 L586 282 Q584 288 578 287 Q572 286 571 279Z','#161312'),
 shape(id+'-catchlight',id==='left-eye'?'M462 322 L467 322 467 326 463 327Z':'M576 275 L581 274 582 279 577 279Z','#fffaf0'),
 shape(id+'-catchlight-small',id==='left-eye'?'M472 331 L474 331 474 333 472 333Z':'M585 287 L588 286 588 289 585 290Z','#fff3bb')
 ],{transform:`translate(${s.gazeX*2} ${(id==='left-eye'?2:3)+(s.gazeY||0)*2})`})],{clip:sclera,...fading}),
 shape(id+'-lower-lid',lower,'#d7735b',fading),
 shape(id+'-upper-lid',lash,'#211615'),
 shape(id+'-eyelashes',lashTips,'#201313')
 ],{transform:eyeTransform,opacity:s.eyeOpen<.18?0:1}),
 shape(id+'-closed-lid',s.eyeOpen<closeAt?lash+' '+lashTips:closed,s.eyeOpen<closeAt?'#211615':'#40211e',
  {opacity:s.eyeOpen<closeAt?1:0,...(s.eyeOpen<closeAt?{transform:eyeTransform}:{})})
 ]);
 }
 const shapes=[
 shape('ear-root-bridge','M638 274 Q652 274 668 285 L696 289 711 300 Q698 316 679 326 L656 340 646 335 647 311Z','#f3aa83'),
 shape('ear-base','M668 250 Q682 238 696 242 Q714 243 720 258 Q724 270 720 283 L707 286 707 296 Q704 307 692 315 L680 323 668 323 Q662 318 662 307 L661 281Z','#dd8968'),
 shape('ear-helix','M670 250 Q685 240 697 245 Q713 249 716 263 L717 279 710 282 708 267 Q704 255 695 253 Q686 250 678 257 L674 269 668 266Z','#ffc5a0'),
 shape('ear-helix-rim-light','M678 249 Q691 244 701 251 L707 258 708 269 704 261 Q699 253 690 253 L680 258 675 258Z','#ffd5ae'),
 shape('ear-concha','M677 264 Q684 256 691 258 Q702 263 700 275 L696 281 686 282 681 291 673 288 675 278Z','#dc785c'),
 shape('ear-antihelix','M680 263 Q688 257 694 263 L697 274 693 278 689 270 685 269 682 281 678 284 676 279Z','#f7af88'),
 shape('ear-concha-deep','M679 280 Q686 275 691 281 L688 289 681 294 676 291Z','#bd644d'),
 shape('ear-tragus','M670 288 L679 285 682 291 677 299 668 302Z','#ffc39a'),
 shape('ear-lobe','M669 299 Q680 305 690 300 L702 293 Q698 306 685 313 L678 320 669 318 666 309Z','#ffcea6'),
 shape('ear-lobe-soft-shade','M687 305 L696 300 694 306 683 316 676 319 670 316 677 312Z','#ee9d7a',{opacity:.57}),
 shape('face-outline','M430 211 Q468 185 503 182 Q521 178 531 195 Q542 224 556 238 Q592 246 616 264 Q642 290 650 326 Q660 349 660 368 Q657 390 643 410 Q624 435 601 456 Q585 472 575 478 L550 478 Q526 465 499 450 Q470 433 451 411 Q430 389 419 361 Q411 347 414 330 Q420 307 423 289 Q426 266 426 239Z','#98503d'),
 shape('face-base','M433 213 Q472 188 501 186 Q518 181 529 197 Q540 223 553 238 Q591 251 614 266 Q638 291 644 322 Q655 347 654 367 Q651 389 639 407 Q619 432 597 452 Q581 467 573 472 L551 472 Q527 459 502 446 Q474 430 455 408 Q434 387 425 359 Q416 347 419 333 Q424 309 427 289 Q430 264 431 239Z','#ffc59f'),
 shape('forehead-light','M438 215 L475 194 511 188 526 197 543 231 552 239 535 252 510 279 490 300 466 279 442 263 433 242Z',light),
 shape('cheek-center-light','M489 318 Q515 325 529 318 Q570 318 610 294 L635 306 646 342 641 369 617 403 587 432 561 454 544 452 517 438 491 417 472 389 468 359Z',light,{opacity:.25}),
 shape('face-left-shadow','M419 333 Q424 346 429 361 Q438 384 456 406 Q474 428 500 445 L482 437 Q454 416 439 394 Q425 373 419 352Z','#dc805f',{opacity:.30}),
 shape('right-jaw-warmth','M649 343 Q658 360 651 381 Q640 406 620 428 L593 454 575 470 552 473 560 470 Q577 467 590 452 Q615 430 634 404 Q647 380 649 360Z','#f1ad85',{opacity:.25}),
 shape('left-cheek-blush','M428 337 Q446 342 462 337 Q479 335 489 347 Q492 356 486 367 Q470 375 451 369 Q434 361 428 345Z','#ed947b',{opacity:.16}),
 shape('right-cheek-blush','M547 301 Q568 301 588 291 Q610 284 630 296 Q636 308 632 322 Q617 339 591 339 Q570 333 553 320Z','#ed947b',{opacity:.16}),
 shape('left-under-eye-soft-plane','M429 340 Q448 348 465 341 L478 337 Q473 347 460 352 Q445 355 433 347Z','#f2ab8c',{opacity:.22}),
 shape('right-under-eye-soft-plane','M546 302 Q568 306 588 295 L612 277 615 282 Q605 299 584 309 L561 316 549 311Z','#efa080',{opacity:.24}),
 shape('left-under-eye-high-plane','M437 361 Q454 368 472 360 L474 364 Q457 373 444 368Z','#ffd2ad',{opacity:.14}),
 shape('right-cheek-high-plane','M588 330 Q610 325 629 313 L632 320 Q616 334 598 338Z','#ffd6b1',{opacity:.13}),
 shape('left-eye-socket','M425 312 Q445 300 467 307 Q484 313 495 328 L492 332 Q476 316 455 315 Q437 315 427 323Z','#e99b80',{opacity:.61}),
 shape('right-eye-socket','M537 291 Q547 272 567 264 L601 252 617 253 615 262 Q586 266 565 280 L541 301Z','#e59178',{opacity:.59}),
 shape('left-brow','M419 300 L432 293 446 291 459 294 472 301 473 305 458 303 444 299 422 307Z','#633626'),
 shape('right-brow','M514 263 L533 252 550 241 562 238 568 243 564 249 552 252 536 262 519 273 514 273Z','#633626'),
 eye('left-eye',465.5,330,-9,scleraL,
 'M445 318 Q461 311 479 319 L481 330 Q479 340 468 343 Q452 344 447 333Z',
 'M411 330 L418 322 Q435 312 452 312 Q472 312 487 324 L493 330 488 332 Q474 320 456 320 Q438 322 426 333 L420 337 410 335Z',
 'M422 334 Q441 347 459 341 Q477 337 490 330 L488 334 Q475 342 460 345 Q440 351 423 339Z',
 'M420 333 Q444 347 480 332 L488 329 484 333 Q449 353 421 338Z'),
 eye('right-eye',577,285,-25,scleraR,
 'M561 272 Q578 264 594 270 L596 282 Q594 294 584 299 Q570 302 564 291Z',
 'M538 299 Q547 279 566 270 Q590 258 611 257 L623 251 620 261 612 268 Q590 270 570 278 Q552 285 545 299 L541 307 538 307Z',
 'M542 301 Q563 307 584 297 Q603 286 613 267 L613 275 Q603 291 586 300 Q565 311 543 306Z',
 'M541 301 Q574 304 608 275 L619 262 616 268 Q585 311 543 305Z'),
 group('brow-to-nose-volume',[
 shape('left-medial-brow-plane','M471 296 Q488 300 499 317 Q505 329 507 343 L511 359 507 363 Q501 349 498 335 Q492 318 481 310 L470 306Z','#e69b7b',{opacity:.13}),
 shape('glabella-saddle','M513 268 L520 266 Q517 281 513 296 L509 312 502 317 503 306 Q509 285 513 268Z','#efb08b',{opacity:.12}),
 shape('bridge-near-plane','M506 341 Q509 346 509 353 L511 362 Q512 367 517 371 L522 375 517 377 Q507 372 504 364 Q503 353 506 341Z','#e88f70',{opacity:.62}),
 shape('bridge-front-light','M511 309 Q515 323 516 340 L518 352 516 357 511 353 Q510 340 508 329Z','#ffd5ad',{opacity:.32}),
 shape('nose-tip-plane','M510 355 Q517 352 524 356 Q530 359 534 365 L532 371 525 375 Q516 373 510 368Z','#ffc09a'),
 shape('nose-tip-underplane','M508 361 Q511 369 519 372 L526 375 525 379 518 377 Q510 374 506 368Z','#d57256',{opacity:.79}),
 shape('near-alar-wing','M532 357 Q541 356 547 363 L547 368 Q541 372 535 372 L534 369 539 365 534 362Z','#f1a884',{opacity:.38}),
 shape('nose-nostril','M535 365 Q540 361 545 364 L546 366 Q539 366 535 369Z','#a84734'),
 shape('nose-tip-highlight','M513 355 L519 354 522 357 520 361 515 362 513 360Z','#ffe9c9'),
 shape('nose-bridge-to-tip-light','M513 344 L516 345 518 352 515 355 512 352Z','#ffdcb4',{opacity:.51})
 ]),
 shape('philtrum','M549 381 L551 387 548 389 546 386Z','#efb088',{opacity:.5}),
 group('reference-lips',[
 // Two upper vermilion lobes meet at the cupid's bow. The mouth corners stay
 // fixed as speaking opens the inner seam and lowers the fuller lower lip.
 shape('upper-lip','M-36 .5 Q-28 -2 -25 -7 Q-23 -14 -18 -12 L-12 -9 Q-9 -13 -5 -12 Q4 -11 13 -5 Q25 1 34 -2 L31 2 Q20 3 11 .4 Q4 -1 -2 1 Q-9 3 -15 1 Q-23 2 -29 3 L-35 2Z','#ed866d'),
 shape('mouth-cavity',`M-36 .5 Q-30 3 -26 1 Q-22 -2 -17 -1 Q-11 2 -6 0 Q0 -2 6 1 Q12 0 19 2 Q27 4 34 -2 L36 -4 35 0 Q34 3 29 ${4+s.mouth*.24} Q20 ${5+s.mouth*1.32} 8 ${3+s.mouth*2.4} Q-2 ${2+s.mouth*2.4} -10 ${3+s.mouth*2.4} Q-19 ${2+s.mouth*1.92} -27 ${5+s.mouth*.6} L-34 4 -37 2Z`,'#963c2f'),
 shape('lower-lip',`M-35 3 Q-32 ${14+s.mouth*.6} -23 ${20+s.mouth*1.44} Q-13 ${27+s.mouth*1.92} -4 ${25+s.mouth*1.92} Q10 ${21+s.mouth*1.44} 20 ${12+s.mouth*.72} L34 1 Q23 ${6+s.mouth*.72} 8 ${3+s.mouth*2.4} Q-2 ${2+s.mouth*2.4} -10 ${3+s.mouth*2.4} Q-19 ${2+s.mouth*1.92} -27 ${5+s.mouth*.6}Z`,'#f59b81'),
 shape('lower-lip-shade',`M-23 ${19+s.mouth*1.44} Q-15 ${23+s.mouth*1.92} -8 ${21+s.mouth*1.92} Q-1 ${20+s.mouth*1.92} 5 ${21+s.mouth*1.44} Q-5 ${28+s.mouth*1.92} -15 ${26+s.mouth*1.92} Q-21 ${24+s.mouth*1.44} -25 ${21+s.mouth*1.44}Z`,'#dc866e',{opacity:.67}),
 shape('lip-highlight',`M-24 ${10+s.mouth*1.44} Q-22 ${8.5+s.mouth*1.44} -20 ${10+s.mouth*1.44} L-21 ${12+s.mouth*1.44} -24 ${12+s.mouth*1.44}Z M-4 ${10+s.mouth*1.92} L-1 ${9.5+s.mouth*1.92} 1 ${10.5+s.mouth*1.92} -1 ${12.5+s.mouth*1.92} -4 ${12.5+s.mouth*1.92}Z`,'#ffe4c8',{opacity:.72})
 ],{transform:'translate(552.5 401.5) rotate(-21.0375)'}),
 shape('chin-highlight','M536 455 Q553 464 575 455 Q568 466 555 468 Q544 465 536 461Z','#ffd5af',{opacity:.22}),
 shape('right-sideburn','M638 283 L644 300 646 321 642 342 634 357 626 367 632 368 640 358 647 343 652 321 649 302 646 290Z','#70402e')
 ];
 // An opening smile reveals a clipped upper tooth plane, not an overlaid sticker.
 // The same live cavity and emotion mapper control its edge and visibility.
 if(s.smileTeeth>0){
  const lips=shapes.find(n=>n.id==='reference-lips'),cavity=lips.children.find(n=>n.id==='mouth-cavity');
  const blend=s.smileTeeth,toHex=v=>Math.round(v).toString(16).padStart(2,'0');
  cavity.fill='#'+[150+(87-150)*blend,60+(43-60)*blend,47+(42-47)*blend].map(toHex).join('');
  lips.children.splice(2,0,group('smile-teeth-clip',[
   shape('smile-upper-teeth','M-27 1 Q-9 4 15 3 L27 0 L24 6 Q0 9 -25 5Z','#fff0d2',{opacity:blend})
  ],{clip:cavity.d}));
 }
 for(const id of ['left-brow','right-brow']){const brow=shapes.find(n=>n.id===id);if(s.brow)brow.transform=`translate(0 ${-s.brow*5})`;}
 return group('face-reference-fit',shapes,{transform:`translate(${tx} ${ty}) scale(${sx})`});
}

/* Shared body attachment anchors, same .29 map as face; not a visual acceptance claim. */
const anatomyAnchors={
 referenceToCanvas:{scale:.29,translate:[-50.56,-12.99]},
 underJaw:[108.94,128.76],rightNeckAtJaw:[143.16,105.85],
 neckBaseLeft:[116.19,163.04],neckBaseRight:[151.28,165.65],sternalNotch:[135.04,168.55],
 rightEarRoot:[139.68,79.17],rightEarStud:[149.25,84.39],rightHoopTop:[150.12,87.0],
 headRegistration:HEAD_REGISTRATION
};
function referenceNeck(s,shape,group){
 // These are final rest-pose anatomical contours in reference space. The +3/0
 // head registration is already accounted for in the mastoid and under-jaw edge.
 // The upper attachment descends to one broad root; no per-coordinate warp.
 const neck=group('reference-neck',[
 shape('neck-continuity-base','M551 455 Q588 447 625 413 L662 370 Q674 379 677 403 Q679 440 676 478 Q675 505 684 537 Q695 570 715 589 Q729 602 752 609 L755 622 Q719 615 690 622 L647 636 Q627 632 604 620 L581 617 Q577 590 568 564 Q556 543 552 520Z','#fcc69e'),
 shape('neck-lateral-plane','M551 463 Q565 481 580 476 Q609 453 632 425 L666 379 672 394 Q658 422 638 448 Q617 472 601 496 Q584 518 567 538 L557 526 553 509Z','#eda580'),
 shape('under-jaw-shadow','M551 463 Q561 478 579 475 Q608 453 631 427 Q652 401 666 378 L669 390 Q650 418 626 443 Q602 470 581 485 Q566 489 554 481Z','#c97356',{opacity:.59}),
 shape('neck-under-jaw-return','M555 482 Q565 490 580 485 Q598 473 613 456 L602 473 Q585 495 571 508 L559 514 556 501Z','#dd8d6b',{opacity:.58}),
 shape('neck-lateral-recess','M553 489 Q557 499 564 503 L576 501 Q571 513 565 523 L567 535 559 527 554 512Z','#d98664',{opacity:.44}),
 shape('neck-shadow-transition','M570 529 Q585 508 602 485 Q621 460 642 436 L661 407 Q652 430 634 453 Q615 479 602 502 Q585 526 573 542 L565 538Z','#f6bc96',{opacity:.80}),
 shape('neck-front-light','M645 451 Q660 443 665 462 Q669 498 679 534 Q690 570 708 590 L722 605 Q696 605 678 616 L649 630 630 624 603 615 Q607 594 609 572 Q610 540 622 511 Q635 483 645 451Z','#ffd0a8',{opacity:.55}),
 shape('neck-tendon-shade','M676 533 Q678 553 672 574 Q665 596 653 615 L646 627 641 629 Q651 610 658 587 Q666 562 671 543Z','#e6a17c',{opacity:.36}),
 shape('neck-mastoid-light','M672 401 Q676 431 671 464 Q670 497 681 536 L680 547 Q668 521 667 494 Q667 470 671 445Z','#ffd5ad',{opacity:.36}),
 shape('collarbone-left','M580 608 Q596 606 611 614 Q628 624 640 626 L641 631 Q624 629 607 621 Q594 614 581 614Z','#e69a77',{opacity:.53}),
 shape('sternal-notch','M638 625 Q645 628 652 624 L650 629 645 632 639 631Z','#dc9170',{opacity:.48}),
 shape('collarbone-right','M652 627 Q671 616 689 614 Q713 611 731 616 L729 621 Q710 616 692 619 Q671 622 654 632Z','#e69a77',{opacity:.47})
 ],{transform:'translate(-50.56 -12.99) scale(.29)'});
 // Two-bone neck skinning: jaw follows the head, root follows the thorax.
 // This permits a bounded head inclination without losing the approved root.
 // When motion is off, the original contour bytes and registration remain exact.
 if(s.breath||s.head||s.headY){
  const angle=s.head*Math.PI/180,c=Math.cos(angle),sn=Math.sin(angle);
  const map=(x,y,earAperture=false)=>{const v=Math.max(0,Math.min(1,(y-440)/190)),w=v*v*(3-2*v);
   const ox=x*.29-50.56,oy=y*.29-12.99;
   const tx=136.5+(ox-136.5)*(1+s.breath*.006)-(s.headX||0)-135.04;
   const ty=344.5+(oy-344.5)*(1+s.breath*.007)-(s.headY||0)-168.55;
   const nx=135.04+tx*c+ty*sn,ny=168.55-tx*sn+ty*c;
   return [x+(nx-ox)*w/.29,y+(ny-oy)*w/.29];};
  for(const n of neck.children)n.d=n.d.replace(/([+-]?(?:\d*\.)?\d+(?:e[+-]?\d+)?)\s+([+-]?(?:\d*\.)?\d+(?:e[+-]?\d+)?)/gi,(_,x,y)=>map(+x,+y).map(v=>+v.toFixed(5)).join(' '));
 }
 return neck;
}

function scene(s){
 const backHair=group('hair-back',[
 shape('hair-silhouette','M37 178 Q18 175 21 156 Q7 157 7 138 Q-13 130 -7 114 Q-3 103 15 95 Q3 89 5 75 Q5 60 24 42 Q30 22 49 16 Q58 2 76 1 Q89 -7 101 7 Q112 -4 126 5 Q134 10 138 15 Q153 15 166 35 Q178 47 167 65 Q188 79 177 98 Q191 113 180 128 Q198 144 181 162 Q188 181 165 187 53 194Z','hairDark'),
 shape('left-volume','M67 70 Q58 91 33 96 Q13 96 2 106 Q-10 114 -6 124 Q-2 136 15 134 Q34 132 46 120 Q43 136 21 146 Q-2 155 -4 169 Q-5 183 14 185 L49 176 69 148 75 120 74 82Z','hair'),
 shape('left-light-ribbon','M62 78 Q48 100 25 103 Q8 105 1 115 Q-5 123 4 130 L9 131 Q-4 127 1 118 Q7 110 24 110 Q49 102 62 85Z','hairLight'),
 shape('left-ribbon-gold','M24 101 Q5 108 0 118 L-1 123 -4 121 -3 115 3 109 11 105Z','hairGold'),
 shape('left-flow-shadow','M54 99 Q46 114 29 120 L14 125 Q7 128 8 132 L15 134 Q33 135 46 122 L52 108Z','hairDeep'),
 shape('left-flow-light','M40 111 Q24 122 14 127 L12 131 17 132 12 134 7 132 6 128 Q15 118 28 116Z','hairMid'),
 shape('left-rear-return-depth','M9 135 Q22 141 38 130 L35 136 24 142 15 143 6 141 -1 136Z','#40261e'),
 shape('left-bottom-sweep','M48 107 Q52 125 30 144 Q33 155 45 149 Q61 139 67 124 Q65 148 48 157 Q37 173 47 180 Q68 176 74 153 L79 134Z','hairMid'),
 shape('left-bottom-light','M48 123 Q43 138 33 144 Q39 150 51 141 L62 129 Q56 145 46 149 L40 153 Q27 156 26 145Z','hairLight'),
 shape('right-volume','M107 15 Q127 8 143 27 Q162 24 167 48 Q161 60 170 72 Q187 83 169 100 Q179 118 183 120 Q188 134 176 143 Q191 160 172 175 L151 161 143 110 128 64Z','hair'),
 shape('right-shadow-ribbon','M125 19 Q143 20 149 37 Q162 48 154 59 Q158 76 170 82 L169 91 Q145 76 141 62 L139 37Z','hairDeep'),
 shape('right-cool-rim','M148 30 L158 38 161 49 159 58 Q161 72 174 81 L173 88 Q156 76 154 60 L156 48 148 37Z','hairCool'),
 shape('right-rear-upper-channel','M151 35 Q159 47 154 57 L157 69 164 76 168 78 169 82 161 77 153 67 150 58 151 48Z','#542f27'),
 shape('right-rear-upper-bounce','M158 42 L160 48 158 57 159 64 163 69 161 69 157 64 156 56 157 49Z','#b0959a'),
 shape('right-rear-upper-warm-strand','M146 53 Q150 64 158 71 L160 76 156 73 148 64Z','#ad7450'),
 shape('right-middle-wave','M151 82 Q163 101 177 109 Q181 120 175 126 Q157 119 148 102 L140 86Z','hairMid'),
 shape('right-rim','M167 100 L179 111 Q185 123 175 128 L170 126 Q179 120 175 115 L164 105Z','hairCool'),
 shape('right-rear-middle-channel','M151 85 Q159 101 172 110 L176 115 175 121 172 123 170 122 173 118 171 113 159 104 152 95Z','#512e27'),
 shape('right-rear-middle-warm-plane','M151 91 Q158 106 168 112 L171 116 169 117 160 111 154 102Z','#ad7251'),
 shape('right-rear-middle-rim-glint','M170 104 L177 110 180 116 179 121 176 124 175 123 177 119 176 114Z','#b1919d'),
 shape('right-bottom-wave','M146 116 Q157 138 176 142 Q183 154 172 165 Q168 150 157 147 L141 137Z','hairDeep'),
 shape('right-bottom-light','M153 119 Q162 135 176 139 L180 149 177 157 Q176 143 166 141 Q150 132 153 119Z','hairLight'),
 shape('right-rear-lower-channel','M151 123 Q159 140 170 144 L175 150 174 155 171 159 172 152 169 149 158 143 153 135Z','#472820'),
 shape('right-rear-lower-copper','M155 128 L160 136 168 141 172 146 169 145 161 141 156 135Z','#c08559'),
 ]);
 const torso=group('shoulder-study',[
 shape('upper-chest','M575 604 L595 614 617 625 639 631 665 620 689 611 707 603 741 655 786 737 823 800 870 864 909 940 488 940 486 850 512 804 538 754 559 688 567 635Z','#fcc69e'),
 shape('upper-chest-light','M621 614 L652 622 681 614 710 609 732 657 771 728 807 793 833 851 787 892 617 895 531 845 551 779 574 697 585 634Z','#ffd0a8',{opacity:.65}),
 shape('visible-collarbone-left','M574 610 Q593 607 608 617 Q619 623 630 626 L633 630 Q617 628 604 622 Q590 616 575 617Z','#eaa17f',{opacity:.4}),
 shape('local-visible-sternal-notch','M634 628 Q639 631 646 628 L645 633 640 635 636 633Z','#df9574',{opacity:.5}),
 shape('visible-collarbone-right','M649 629 Q662 618 676 614 Q694 608 709 613 L709 618 Q690 614 676 619 Q662 622 651 633Z','#eaa17f',{opacity:.38}),
 shape('left-jacket-outline','M205 589 L279 568 348 610 456 679 508 783 505 914 171 953 122 823 158 666Z','jacketDeep'),
 shape('left-jacket-plane','M207 608 L271 591 337 639 437 707 476 796 469 926 188 950 149 823 177 676Z','jacket'),
 shape('left-jacket-fold','M214 622 L259 679 244 765 264 866 216 923 192 785Z','jacketLight'),
 shape('left-lapel-plane','M270 588 L355 622 454 678 426 704 476 746 486 789 379 730 295 685Z','jacketLight'),
 shape('left-lapel-edge','M272 590 L301 661 378 713 446 748 449 754 374 719 295 666 266 592Z','gold'),
 shape('right-jacket-outline','M676 503 L716 504 852 590 852 609 822 627 853 654 900 682 944 755 905 905 818 777 753 670 711 603Z','jacketDeep'),
 shape('right-jacket-plane','M691 513 L718 518 837 591 814 608 784 617 826 653 866 678 898 736 903 824 816 713 750 640 709 588Z','jacket'),
 shape('right-lapel-plane','M696 517 L721 524 832 592 785 617 792 632 847 660 834 687 746 629 716 583Z','jacketLight'),
 shape('right-lapel-edge','M697 515 L724 525 839 592 839 598 791 620 797 630 850 658 847 665 790 635 784 615 829 594 721 531Z','gold'),
 shape('right-lapel-stud','M837 682 L850 682 854 690 850 700 837 700 832 692Z','gold'),
 shape('right-lapel-stud-light','M839 684 L848 684 849 689 837 689Z','goldLight'),
 shape('camisole-left-hint','M493 836 L517 814 553 848 590 889 627 928 517 940 482 914Z','ivory'),
 shape('camisole-left-trim','M514 810 L535 828 565 860 602 898 627 925 624 932 597 907 558 868 529 837 509 819Z','white'),
 shape('camera-strap-left','M489 761 L509 766 511 941 491 941Z','jacketDeep'),
 shape('necklace-chain','M575 615 L584 629 599 646 615 661 635 676 658 687 676 680 689 660 705 634 716 607 720 611 708 638 692 665 679 685 659 693 632 681 612 666 595 651 580 633 571 617Z','gold'),
 shape('necklace-glints','M580 622 L584 621 589 630 585 632Z M601 648 L604 645 611 651 608 655Z M635 675 L638 672 645 677 643 681Z M702 640 L705 633 709 634 706 642Z','goldLight'),
 shape('necklace-pendant','M646 699 L666 698 679 711 678 733 666 745 645 744 633 732 634 711Z','gold'),
 shape('necklace-pendant-inset','M647 705 L664 704 673 714 672 730 663 738 648 737 640 728 640 714Z','#835923'),
 shape('necklace-pendant-emblem','M653 706 L658 706 658 717 669 712 670 716 661 721 669 728 666 732 658 725 658 735 653 735 653 725 644 731 642 727 650 721 641 717 643 713 653 718Z','goldLight')
 ],{transform:`translate(-50.56 ${-12.99+s.breath}) scale(.29)`});
 const face=referenceFace(s,shape,group);
 const hairTransition=group('left-front-branch-junction',[
 shape('root-to-side-main','M79 74 Q73 87 72 99 Q72 114 84 126 Q94 137 98 148 L100 157 91 153 Q87 139 78 133 Q64 122 62 108 Q60 93 69 80Z','hairDeep'),
 shape('root-to-side-body','M76 80 Q70 98 74 111 Q78 121 88 129 Q96 138 97 149 L93 148 Q91 138 82 132 Q70 124 68 112 Q64 99 71 86 L74 82Z','hair'),
 shape('root-to-side-flow','M73 87 Q69 102 75 115 Q80 124 87 128 L91 135 Q76 127 71 116 Q65 102 73 87Z','hairLight',{opacity:.65}),
 shape('front-curl-inner-channel','M72 91 Q69 104 75 115 Q80 122 87 128 L91 136 88 134 Q78 127 72 118 Q66 107 69 98Z','#48291f'),
 shape('front-curl-inner-crest','M72 95 Q70 107 77 116 L85 125 86 129 Q78 123 73 116 Q68 106 72 95Z','#b97a50'),
 shape('front-curl-return-light','M80 123 L86 129 91 137 93 144 92 146 89 137 85 131Z','#9c5c3e'),
 shape('branch-overlap-shadow','M72 110 Q77 124 88 130 L91 139 Q75 132 68 118Z','hairDark',{opacity:.45}),
 shape('front-curl-split-shadow','M63 96 Q56 110 42 117 L33 122 Q36 126 43 127 L50 124 47 128 Q35 134 29 126 Q27 121 34 117 L47 112Z','#42271f'),
 shape('front-curl-split-body','M61 101 Q54 113 41 119 L34 122 35 125 41 126 47 124 42 129 Q33 130 31 126 Q28 122 34 119 L47 114Z','#8f543b'),
 shape('front-curl-split-light','M59 105 Q52 114 40 119 L33 122 33 124 35 126 33 126 31 124 32 121 Q44 116 51 112Z','#c38a5d'),
 ]);
 const fringe=group('hair-front',[
 group('neck-framing-curl',[
 shape('neck-curl-outline','M84 127 Q100 132 106 150 Q111 163 105 178 Q104 184 99 189 Q108 195 104 206 Q103 220 87 224 L72 224 76 217 Q91 216 93 208 Q80 211 77 201 Q76 193 85 187 Q96 180 94 168 Q86 178 77 175 Q68 172 75 164 Q90 153 86 143Z','hairDark'),
 shape('neck-curl-main','M87 133 Q99 139 103 153 Q107 166 101 178 Q99 185 94 190 Q103 197 99 208 Q94 221 79 221 L78 219 Q95 215 96 204 Q81 210 81 201 Q81 195 89 188 Q101 178 97 163 Q87 175 78 171 L78 167 Q96 155 91 143Z','hair'),
 shape('neck-curl-upper-light','M90 135 Q103 146 103 157 Q105 170 96 181 L87 190 Q82 196 84 201 Q89 208 96 202 L97 198 Q94 204 88 201 Q86 198 92 192 Q107 181 107 164 Q109 146 96 137Z','hairMid'),
 shape('neck-curl-sweep-light','M93 145 Q100 154 98 164 Q92 174 82 174 L77 172 78 170 Q87 172 95 163 Q98 156 93 145Z','hairLight'),
 shape('neck-curl-lower-band','M98 188 Q108 200 99 213 Q90 226 74 224 L78 220 Q96 220 101 207 Q104 198 98 188Z','hairLight'),
 shape('neck-curl-lower-fine','M97 193 Q102 203 94 211 Q86 218 78 216 L81 214 Q96 212 98 204Z','hairMid'),
 shape('neck-curl-dark-seam','M91 169 Q88 180 79 186 Q74 193 79 200 L82 201 Q78 193 83 189 Q93 180 94 169Z','hairDeep'),
 shape('neck-curl-root-fine','M91 135 Q99 143 101 151 L102 159 Q98 143 91 139Z','hairLight',{opacity:.65}),
 shape('neck-curl-root-channel','M89 137 Q99 149 100 159 L99 168 96 173 97 163 Q97 149 89 140Z','#502d23'),
 shape('neck-curl-root-shine','M93 142 Q101 151 101 161 L99 164 99 156 96 148Z','#d29462'),
 shape('neck-curl-underturn','M88 175 Q85 182 81 186 L79 192 80 197 78 197 77 191 80 184Z','#a76947'),
 shape('neck-curl-split-flare','M98 174 Q95 184 89 190 L86 195 86 198 84 196 86 189 92 183Z','#4f2b22'),
 shape('neck-curl-lower-shine','M99 198 Q102 207 93 215 L88 218 82 219 86 216 93 212 97 207Z','#d69564'),
 shape('neck-curl-tip-fine','M85 221 Q98 219 103 209 L102 214 96 220 86 223 80 223Z','#884b36'),
 ]),
 // Large crown planes establish the silhouette before smaller strand facets.
 shape('crown-left','M12 80 Q5 71 14 58 Q22 43 35 32 Q39 17 56 12 Q61 2 77 1 Q87 -6 98 3 L106 13 104 29 101 40 Q91 40 82 46 L76 49 75 55 72 63 72 66 73 70 71 73 70 80 70 89 Q60 98 46 102 Q28 109 12 99 L23 91 Q14 89 12 80Z','hairDark'),
 shape('crown-left-body','M16 78 Q12 70 20 57 Q28 44 40 36 Q43 23 59 18 Q65 8 78 7 Q88 1 97 7 L102 15 101 29 97 37 Q87 41 80 47 Q74 54 70 68 Q66 83 53 93 Q35 106 18 99 L31 89 Q20 89 16 78Z','hair'),
 shape('crown-left-shadow','M96 13 Q83 12 71 25 Q59 36 54 51 Q47 66 32 81 L22 86 Q42 83 55 71 Q66 59 70 43 Q78 29 98 26 L99 35 Q89 38 81 44 Q72 51 68 66 Q61 84 47 93 L32 99 22 97 Q48 85 55 69 L61 48 Q69 28 96 18Z','hairDeep'),
 shape('crown-left-light','M91 9 Q80 6 67 18 Q56 27 47 32 Q42 38 39 49 Q35 64 23 77 L19 80 Q26 82 33 75 Q47 64 53 47 Q58 33 69 27 Q81 19 98 20 L98 16Z','hairLight'),
 shape('crown-left-glint','M86 10 Q73 9 64 20 Q52 28 46 34 L43 45 37 58 31 65 27 67 34 55 39 41 Q42 30 53 25 L63 16 75 11Z','hairGold'),
 shape('crown-left-ridge-turn','M86 13 Q72 17 64 27 Q57 34 52 44 L49 54 44 63 39 68 41 62 46 51 49 41 55 30 64 23 73 19Z','#a26542'),
 shape('crown-left-ridge-light','M77 17 Q66 23 59 33 L55 42 51 52 47 57 45 58 49 49 52 38 58 28 67 22Z','#d59a64'),
 shape('crown-left-ridge-shadow','M93 19 Q79 22 73 31 L68 40 67 45 64 49 65 40 70 31 78 25 88 21Z','#73412d'),
 shape('crown-left-ridge-facet','M68 20 L62 24 55 30 52 37 49 42 49 37 54 28 62 23Z','#efbb7e'),
 shape('crown-upper-crest-plane','M47 23 Q56 12 66 12 L77 5 86 3 92 6 87 8 79 8 69 14 64 19 54 21Z','#a96947'),
 shape('crown-upper-crest-glint','M59 16 L67 9 77 5 82 5 80 8 73 10 67 15 63 16Z','#efbd82'),
 shape('crown-root-inner-plane','M72 31 Q86 23 96 27 L99 34 96 37 Q85 35 77 46 L70 60 65 72 62 76 Q68 57 70 46Z','#99583e'),
 shape('crown-root-recess','M80 30 Q88 25 96 27 L98 31 Q88 29 82 34 L77 41 72 46 74 39Z','#44271f'),
 shape('crown-root-second-recess','M79 40 Q87 33 96 36 L98 39 94 39 Q86 38 81 44 L76 48 76 45Z','#38221c'),
 shape('crown-inner-gloss','M71 40 Q78 30 88 29 L87 32 80 36 77 42 72 53 68 61 67 61Z','#c28357'),
 shape('crown-inner-root-channel','M95 33 L98 36 101 39 97 40 93 39 88 40 82 44 80 44 85 39 91 36Z','#34211c'),
 shape('crown-outer-separated-lock','M42 34 Q26 46 15 63 Q7 78 17 85 L22 86 19 89 11 86 6 79 7 69 12 59 22 47 31 40Z','#683b2d'),
 shape('crown-outer-lock-rim','M38 37 Q23 49 14 65 Q8 77 15 84 L19 85 18 87 12 84 9 79 10 70 14 61 22 50 30 43Z','#c18759'),
 shape('crown-outer-lock-glint','M25 48 L18 57 13 67 12 73 13 78 11 77 11 69 16 57 22 50Z','#e5ae76'),
 shape('crown-middle-separated-lock','M81 24 Q66 29 59 43 Q54 59 45 71 Q34 86 19 94 L14 98 Q35 102 54 88 Q66 77 70 61 L72 48 Q74 34 81 29Z','#9a5b3f'),
 shape('crown-middle-lock-shadow','M80 28 Q69 35 65 48 Q63 67 52 80 Q42 92 28 95 L23 95 Q42 85 51 70 Q58 61 60 47 Q65 32 80 28Z','#4e2c21'),
 shape('crown-middle-lock-light','M78 28 Q68 38 64 51 Q59 72 46 83 Q35 91 23 94 L18 94 Q35 88 43 79 Q54 66 59 46 Q65 32 78 28Z','#c28a5e'),
 shape('crown-middle-lock-rim','M65 42 Q61 60 52 73 L42 83 33 88 27 89 36 84 46 73 53 61 58 46Z','#dfa56e'),
 shape('crown-middle-lock-turn','M50 78 Q39 93 26 97 L19 98 24 100 32 99 43 94 52 86 58 76 55 77Z','#7c4431'),
 shape('crown-temple-subdivision','M67 64 Q58 84 47 93 Q34 104 19 101 L11 98 12 101 Q24 109 40 102 Q60 94 67 76Z','#4a2a20'),
 shape('crown-part-root-depth','M99 12 L103 16 102 27 101 35 99 39 96 38 98 30 98 23Z','#34201b'),
 shape('face-frame-left','M84 40 Q74 49 69 66 Q66 84 54 95 Q40 108 23 112 Q8 115 4 109 Q11 115 26 118 Q46 118 60 102 Q71 88 73 70 L75 57 79 48Z','hairDark'),
 shape('left-temple-substrand','M79 46 Q71 61 69 74 Q65 96 50 106 Q36 117 20 113 L13 109 Q29 113 46 104 Q62 94 68 76 L72 59Z','hairMid'),
 shape('face-frame-left-highlight','M73 58 Q70 83 56 99 Q42 114 22 110 L16 107 Q36 110 51 97 Q65 85 73 58Z','hairLight'),
 shape('face-frame-left-crest','M65 82 Q57 100 42 106 L31 109 24 108 19 105 Q40 108 55 94Z','#e3a671'),
 shape('face-frame-left-turn-shadow','M57 103 Q45 117 28 118 L20 116 16 113 26 116 Q44 115 57 103Z','#48281f'),
 shape('crown-right','M101 17 L103 6 Q113 -2 124 6 Q130 10 136 17 Q149 19 155 34 Q163 43 155 53 L143 55 Q148 61 155 66 L148 72 Q140 68 130 60 L114 52 Q105 41 103 32 L99 29Z','hair'),
 shape('crown-right-shadow','M105 26 Q119 21 130 31 L142 42 134 44 Q121 32 110 36 L107 40 103 35Z','hairDeep'),
 shape('crown-right-light','M105 19 Q118 14 130 24 Q143 27 149 39 L141 34 131 30 121 23 113 24 104 29Z','hairLight'),
 shape('right-crown-root-turn','M103 14 L106 7 Q115 2 124 10 L134 20 144 24 150 31 144 29 136 27 128 21 120 16 113 15 107 18 103 23Z','#9e6445'),
 shape('right-crown-root-glint','M105 9 L111 6 116 6 122 10 124 13 116 10 110 12 105 17Z','#e7b47e'),
 shape('right-crown-upper-fold','M108 19 Q117 12 127 21 L133 26 137 28 130 27 123 23 117 20 111 22 106 26Z','#66382a'),
 shape('right-crown-middle-turn','M109 25 Q120 19 133 31 L140 36 143 41 139 40 131 34 123 29 116 27 111 28Z','#b97d58'),
 shape('right-crown-split','M110 31 Q121 25 133 38 L138 43 135 44 129 38 120 33 113 33 110 36Z','#502e23'),
 shape('right-crown-soft-edge','M134 29 L140 33 147 39 148 43 146 46 144 42 140 37Z','#aa795d'),
 shape('right-face-fringe','M109 37 Q122 38 130 49 Q134 57 147 64 L151 69 Q138 68 126 58 L116 47 110 43 104 40Z','hairMid'),
 shape('right-face-fringe-shadow','M109 43 Q116 42 122 51 L129 59 143 67 139 69 Q127 64 119 55 L108 48Z','hairDeep'),
 shape('right-front-substrand','M112 36 Q123 37 132 49 Q139 59 149 64 L147 66 Q133 61 127 50 Q122 41 112 40Z','hairLight',{opacity:.6}),
 shape('right-front-separation','M110 44 Q117 43 126 54 Q136 65 147 68 L139 67 Q128 63 122 54 Q116 47 110 46Z','hairDark',{opacity:.72}),
 shape('right-face-fringe-glint','M116 38 Q128 40 133 50 L140 59 133 56 127 47 119 43Z','hairLight'),
 shape('right-fringe-root-plane','M111 37 Q122 40 128 48 L135 57 143 63 140 63 132 58 124 50 119 44 112 41Z','#bd835a'),
 shape('right-fringe-fine-glint','M116 40 L121 42 127 48 130 53 127 51 122 47 119 44Z','#d59a6b'),
 shape('right-fringe-lower-separation','M116 48 Q124 54 128 61 L139 67 140 69 134 67 124 60 119 54Z','#512d24'),

 group('camera-hair-clip',[
 shape('camera-outline','M-9 -7 L-6 -8 -5 -10 3 -10 5 -7 10 -7 10 6 -9 6Z','ink'),
 shape('camera-gold-body','M-8 -6 L-5 -7 -4 -9 2 -9 4 -6 9 -6 9 5 -8 5Z','gold'),
 shape('camera-light','M-7 -5 L7 -5 7 -3 -5 -3 -5 4 -7 4Z','goldLight'),
 shape('camera-inset','M-4 -4 L5 -4 7 -2 7 2 4 4 -3 4 -5 1 -5 -2Z','silver'),
 shape('camera-lens','M-1 -3 L3 -3 5 -1 5 2 2 3 -1 2 -3 0Z','ink'),
 shape('camera-reflection','M0 -2 L2 -2 2 -1 0 0Z','white')
 ],{transform:'translate(145 36) rotate(-12)'}),
 group('earring-attachment',[
 shape('earring-hair-shadow','M665 331 Q681 326 697 333 L706 345 Q709 356 702 367 L695 374 681 373 670 366 665 353Z','hairDark'),
 shape('right-ear-stud','M681 315 Q685 312 689 316 L690 321 686 325 681 322Z','gold'),
 shape('right-ear-stud-light','M682 315 L686 315 687 318 684 320 682 318Z','goldLight'),
 shape('right-ear-link','M685 322 L689 322 692 329 691 334 687 333 688 327Z','gold'),
 shape('right-ear-hoop','M677 329 Q689 325 699 333 Q706 341 704 352 Q703 363 693 367 Q681 371 674 362 Q668 353 670 342 Q671 334 677 329Z M679 337 Q674 344 676 353 Q678 361 687 362 Q696 362 699 353 Q701 344 695 337 Q688 331 681 335Z','gold',{fillRule:'evenodd'}),
 shape('right-ear-hoop-glint','M676 336 L679 334 677 341 676 350 678 357 676 358 Q671 349 674 340Z M695 333 Q702 339 702 348 L700 350 Q700 341 695 337Z','goldLight'),
 shape('right-hoop-lower-gold-shade','M677 357 L683 362 690 364 698 361 702 356 700 362 690 368 679 364Z','#aa762b'),
 shape('right-hoop-lower-bevel','M681 361 L687 363 693 362 697 360 697 363 690 365 684 364Z','#e8bd67'),
 shape('left-ear-stud','M440 395 L446 396 448 400 443 403 439 400Z','gold'),
 shape('left-ear-link','M443 400 L447 401 446 407 442 410 440 408Z','gold'),
 shape('left-ear-hoop','M438 405 L451 403 460 412 460 425 454 435 441 437 430 431 428 418 431 408Z M435 412 L433 420 435 427 443 431 451 429 455 423 454 414 448 409Z','gold',{fillRule:'evenodd'}),
 shape('left-ear-hoop-glint','M432 412 L435 410 434 421 438 429 435 429 431 423Z','goldLight')
 ],{transform:'translate(-50.56 -12.99) scale(.29)'})
 ]);
 // Shared art-space negative-space apertures; no runtime or anchor change.
 backHair.clip='M-20 -20 L240 -20 240 330 -20 330Z M21 59 Q12 69 14 77 Q19 72 23 61 L24 57 Q20 65 17 69 Q17 64 21 59Z M4 115 Q0 120 3 125 L6 127 7 124 Q4 121 8 116 L16 112 Q10 112 4 115Z';
 // The upper ear peeks through the foreground crown. This is one anatomical
 // occlusion aperture; its existing helix/concha geometry stays in the face layer.
 fringe.clip='M-20 -20 L240 -20 240 330 -20 330Z M21 59 Q12 69 14 77 Q19 72 23 61 L24 57 Q20 65 17 69 Q17 64 21 59Z M4 115 Q0 120 3 125 L6 127 7 124 Q4 121 8 116 L16 112 Q10 112 4 115Z M144.0 58.6 L143.8 62.8 Q146.5 67.2 151.4 69.7 L158.2 68.9 158.5 63.9 Q157.5 58.1 151.4 56.9 Q147.5 55.8 144.0 58.6Z';
 const strand=group('articulated-lock-root',[
 shape('lock-root','M-8 -8 Q-15 11 -10 25 L-1 32 10 20 11 7 4 -12Z','hairDeep'),
 shape('lock-root-body','M-6 -6 Q-12 10 -6 21 L-1 26 6 18 8 4 3 -9Z','hair'),
 shape('lock-root-substrand','M0 -9 Q-5 6 1 19 L3 20 Q-1 7 3 -7Z','hairMid'),
 shape('lock-root-highlight','M-5 -1 Q-8 11 -2 19 L1 19 -2 22 Q-12 15 -5 -1Z','hairLight'),
 group('articulated-lock-middle',[
 shape('lock-mid','M-5 -6 Q7 6 3 18 Q-4 34 -19 28 Q-30 22 -22 10 Q-27 26 -14 23 Q-2 21 -5 7Z','hairDark'),
 shape('lock-mid-body','M-4 -5 Q10 10 1 20 Q-7 33 -20 26 Q-29 22 -24 14 Q-25 23 -14 23 Q-2 18 -5 7Z','hair'),
 shape('lock-mid-substrand','M-1 2 Q5 14 -5 22 Q-13 29 -22 23 L-20 26 Q-9 31 0 20 Q6 11 -1 2Z','hairDark',{opacity:.65}),
 shape('lock-mid-highlight','M0 0 Q10 16 -5 24 Q-15 30 -23 23 L-24 19 Q-13 27 -4 20 Q3 13 0 0Z','hairLight'),
 group('articulated-lock-tip',[
 shape('lock-tip','M-9 -7 Q4 2 -2 12 Q-10 24 -27 14 Q-35 9 -30 0 Q-31 11 -19 11 Q-7 10 -9 -7Z','hairDeep'),
 shape('lock-tip-light','M-6 -4 Q4 11 -13 16 Q-22 17 -29 9 Q-18 15 -9 9 Q-4 5 -6 -4Z','hairMid'),
 shape('lock-tip-substrand','M-6 0 Q-5 10 -15 12 L-25 10 Q-17 16 -10 12 Q-3 8 -6 0Z','hairLight',{opacity:.65}),
 shape('lock-tip-glint','M-4 3 Q-8 17 -23 12 L-17 13 Q-9 12 -4 3Z','hairLight')
 ],{transform:`translate(-5 22) rotate(${s.strand3})`,pivot:[-5,22]})
 ],{transform:`translate(-1 21) rotate(${s.strand2})`,pivot:[-1,21]})
 ],{transform:`translate(71 107) rotate(${s.strand})`,pivot:[71,107]});
 return {width:W,height:H,palette,anatomyAnchors,hairTopology,layers:[group('neck-rig',[referenceNeck(s,shape,group)],{transform:`translate(${s.headX} ${s.headY||0}) rotate(${s.head} 135.04 168.55)`}),torso,group('head-rig',[backHair,hairTransition,face,fringe,strand],{transform:`translate(${s.headX} ${s.headY||0}) rotate(${s.head} 135.04 168.55)`})]};
}
// The rear hair is rendered behind the shoulders while sharing the head transform.
function orderedScene(s){const r=scene(s),head=r.layers[2],back=head.children.shift();const register=n=>({...n,transform:`translate(${HEAD_REGISTRATION.x} ${HEAD_REGISTRATION.y})`+(n.transform?' '+n.transform:'')});head.children=head.children.map(register);head.staticRegistration=HEAD_REGISTRATION;r.layers.unshift(group('rear-hair-rig',[register(back)],{transform:head.transform,staticRegistration:HEAD_REGISTRATION}));return r;}
// Bounded relative yaw of an authored neutral view. Semantic surfaces carry
// different depths; this is editable 2D projection, not a full 3D head model.
// Apply after blink/expression so their aperture and clipping travel together.
function articulate(scene,pose={}){
 const bound=(v,a,b)=>Math.max(a,Math.min(b,Number.isFinite(v)?v:0));
 const yaw=pose.running===false?0:bound(pose.yaw,-15,15);
 const follow=pose.running===false?0:bound(pose.shoulderFollow,-1,1);
 const raise=pose.running===false?0:bound(pose.shoulderRaise,0,1);
 const lean=pose.running===false?0:bound(pose.listeningLean,0,1);
 if(!yaw&&!follow&&!raise&&!lean)return scene;
 const smooth=v=>{v=bound(v,0,1);return v*v*(3-2*v);};
 const ID=[1,0,0,1,0,0],rad=yaw*Math.PI/180,cs=Math.cos(rad),sn=Math.sin(rad);
 const mul=(a,b)=>[a[0]*b[0]+a[2]*b[1],a[1]*b[0]+a[3]*b[1],a[0]*b[2]+a[2]*b[3],a[1]*b[2]+a[3]*b[3],a[0]*b[4]+a[2]*b[5]+a[4],a[1]*b[4]+a[3]*b[5]+a[5]];
 const point=(m,x,y)=>[m[0]*x+m[2]*y+m[4],m[1]*x+m[3]*y+m[5]];
 const inverse=m=>{const d=m[0]*m[3]-m[1]*m[2];return [m[3]/d,-m[1]/d,-m[2]/d,m[0]/d,(m[2]*m[5]-m[3]*m[4])/d,(m[1]*m[4]-m[0]*m[5])/d];};
 function matrix(value){let m=ID;for(const item of (value||'').matchAll(/(translate|rotate|scale)\(([^)]+)\)/g)){
  const a=item[2].trim().split(/[ ,]+/).map(Number);let n;
  if(item[1]==='translate')n=[1,0,0,1,a[0],a[1]||0];
  else if(item[1]==='scale')n=[a[0],0,0,a[1]??a[0],0,0];
  else{const r=a[0]*Math.PI/180,c=Math.cos(r),s=Math.sin(r);n=[c,s,-s,c,0,0];if(a.length===3)n=mul(mul([1,0,0,1,a[1],a[2]],n),[1,0,0,1,-a[1],-a[2]]);}
  m=mul(m,n);
 }return m;}
 const mapPath=(d,map)=>d.replace(/([+-]?(?:\d*\.)?\d+(?:e[+-]?\d+)?)\s+([+-]?(?:\d*\.)?\d+(?:e[+-]?\d+)?)/gi,(_,x,y)=>map(+x,+y).map(v=>+v.toFixed(5)).join(' '));
 const find=(nodes,id)=>{for(const n of nodes){if(n.id===id)return n;const r=find(n.children||[],id);if(r)return r;}};
 const head=find(scene.layers,'head-rig');if(!head)throw new Error('Yaw requires the adopted head rig');
 const headMatrix=matrix(head.transform),headInverse=inverse(headMatrix);
 // One thorax surface: neck root, clavicles, trapezius, sleeves and upper arms
 // share the same field. It is exactly zero at the wrists, camera and pelvis.
 function shoulder(x,y){
  const w=smooth((y-122)/43)*(1-smooth((y-180)/122));
  const left=Math.exp(-(((x-55)/64)**2)),side=bound((x-135)/100,-1,1);
  return [x+w*(follow*1.7+lean*1.1),y+w*(follow*1.05*side-raise*2.4*left-lean*.55)];
 }
 function project(x,y,part,id){
  // The adopted facial horizontal is tilted -22 degrees in its neutral art.
  // Ellipsoidal cheek depth foreshortens the far eye; the nose/lips protrude.
  const rx=(x-3+50.56)/.29,ry=(y+12.99)/.29;
  const u=(rx-535)*.927-(ry-335)*.375;
  const v=(rx-535)*.375+(ry-335)*.927;
  let depth,weight=1;
  if(part==='face'||part==='neck'||part==='jewelry'){
   depth=75*Math.sqrt(Math.max(.035,1-(u/178)**2))*Math.max(.35,1-Math.abs(v)/410);
   if(/nose|alar|glabella|bridge-|philtrum/.test(id))depth+=40*Math.exp(-(((v-15)/120)**2));
   if(/lip|mouth|teeth/.test(id))depth+=18;
   if(/^ear-|^right-ear-|^right-hoop-|^earring-hair/.test(id))depth=-19;
   if(part==='neck')weight=1-smooth((ry-445)/175);
  }else{
   depth=part==='rear'?-28:23;
   // Root moves with the crown; hanging ends retain their shoulder attachment.
   weight=1-smooth((y-115)/145);
   if(/face-fringe|sideburn|face-frame|crown/.test(id))depth=38;
  }
  let shift=(u*(cs-1)+depth*sn)*.29*weight;
  // The visible right ear narrows as it turns behind the cheek. Its attachment
  // remains continuous; the foreground fringe also overlaps it geometrically.
  if(/^ear-|^right-ear-|^right-hoop-|^earring-hair/.test(id))shift+=(rx-665)*(Math.max(.48,1-yaw*.027)-1)*.29;
  return [x+shift*.927,y-shift*.375];
 }
 const rigid=new Set(['camera-rig','hands-front-of-camera','waist-and-trousers']);
 function walk(node,parent=ID,part='body'){
  if(rigid.has(node.id))return node;
  let kind=part;
  if(node.id==='head-rig')kind='hair';
  if(node.id==='rear-hair-rig')kind='rear';
  if(node.id==='flowing-shoulder-hair-rig')kind='hair';
  if(node.id==='face-reference-fit')kind='face';
  if(node.id==='neck-rig')kind='neck';
  if(node.id==='earring-attachment')kind='jewelry';
  // Root layout is a fixed framing registration, excluded from anatomy space.
  const m=node.id==='composition-layout'?ID:mul(parent,matrix(node.transform)),inv=inverse(m);
  const map=(x,y,earAperture=false)=>{
   let q=point(m,x,y);
   if(kind!=='body'){
    let p=point(headInverse,...q);p=project(...p,earAperture?'face':kind,earAperture?'ear-base':node.id);q=point(headMatrix,...p);
    if(kind==='neck'){const w=smooth((q[1]-116)/52),r=shoulder(...q);q=[q[0]+(r[0]-q[0])*w,q[1]+(r[1]-q[1])*w];}
   }else q=shoulder(...q);
   return point(inv,...q);
  };
  return {...node,...(node.d?{d:mapPath(node.d,map)}:{}),...(node.clip?{clip:mapPath(node.clip,(x,y)=>map(x,y,node.id==='hair-front'&&x>140&&x<161&&y>54&&y<73))}:{}),
   ...(node.children?{children:node.children.map(n=>walk(n,m,kind))}:{})};
 }
 return {...scene,layers:scene.layers.map(n=>walk(n)),articulation:{kind:'limited-relative-yaw',degrees:yaw,shoulderFollow:follow,shoulderRaise:raise,listeningLean:lean}};
}

function xml(v){return String(v).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function nodeSVG(n){const attrs=` id="${xml(n.id)}"${n.transform?` transform="${xml(n.transform)}"`:''}${n.opacity!==undefined?` opacity="${n.opacity}"`:''}`;const clip=n.clip?`<defs><clipPath id="${n.id}-clip"><path d="${n.clip}"/></clipPath></defs>`:'';return n.type==='group'?`<g${attrs}>${clip}<g${n.clip?` clip-path="url(#${n.id}-clip)"`:''}>${n.children.map(nodeSVG).join('')}</g></g>`:`<path${attrs} fill="${n.fill}"${n.fillRule?` fill-rule="${n.fillRule}"`:''} d="${n.d}"/>`;}
function svg(s){const r=orderedScene(s);return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="MIRA code-native face and hair study">${r.layers.map(nodeSVG).join('')}</svg>`;}
function transform(ctx,t){const re=/(translate|rotate|scale)\(([^)]+)\)/g;let m;while((m=re.exec(t||''))){const a=m[2].trim().split(/[ ,]+/).map(Number);if(m[1]==='translate')ctx.translate(a[0],a[1]||0);else if(m[1]==='scale')ctx.scale(a[0],a[1]??a[0]);else {if(a.length===3)ctx.translate(a[1],a[2]);ctx.rotate(a[0]*Math.PI/180);if(a.length===3)ctx.translate(-a[1],-a[2]);}}}
function drawNode(ctx,n){ctx.save();transform(ctx,n.transform);if(n.clip)ctx.clip(new Path2D(n.clip));if(n.opacity!==undefined)ctx.globalAlpha*=n.opacity;if(n.type==='group')n.children.forEach(v=>drawNode(ctx,v));else {ctx.fillStyle=n.fill;ctx.fill(new Path2D(n.d),n.fillRule||'nonzero');}ctx.restore();}
function render(ctx,s){ctx.clearRect(0,0,W,H);orderedScene(s).layers.forEach(n=>drawNode(ctx,n));}
const API={articulate,W,H,HEAD_REGISTRATION,palette,anatomyAnchors,hairTopology,stateAt,scene:orderedScene,svg,render};
if(typeof module!=='undefined'&&module.exports)module.exports=API;root.MiraCharacter=API;
})(typeof window!=='undefined'?window:globalThis);
