'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const source=fs.readFileSync(__dirname+'/../../assets/overlay-pdf2htmlex.js','utf8');const code=source.slice(source.indexOf('var preparedViewers'),source.indexOf('export function createPdf2htmlEx'));
 const {preparePdf2htmlEx}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
 function setup(count=606){
  let nativeReads=0;
  const prototype={height(){return this.page.clientHeight;},hide(){},show(){},view_position(){return [0,0];}};
  const frames=Array.from({length:count},(_,i)=>{
   const n=i+1;
   const pc={get clientHeight(){nativeReads++;if(n!==1)throw Error('offscreen layout forced');return 601;}};
   const pi={getAttribute(name){return name==='data-data'?JSON.stringify({ctm:[1,0,0,1,n,0]}):null;}};
   return {id:'pf'+n.toString(16),classList:{contains(c){return c==='pf';}},getAttribute(name){return name==='data-page-no'?n.toString(16):name==='data-pdf2html-page-size'?'400,600,601':null;},querySelector(s){return s==='.pc'?pc:s==='.pi'?pi:null;}};
  });
  const container={children:frames,childNodes:frames};
  let findCalls=0;
  const viewer={container,find_pages(){findCalls++;this.pages=this.container.childNodes.map(frame=>{const p=Object.create(prototype);p.page=frame;p.original_height=frame.querySelector('.pc').clientHeight;return p;});},render(){throw Error('full-book render ran');},schedule_render(){throw Error('render timer armed');}};
  const document={documentElement:{getAttribute(){return 'v1';}},getElementById(){return container;}};
  const window={pdf2htmlEX:{defaultViewer:viewer},clearTimeout(){}};
  return {document,window,viewer,frames,container,prototype,reads:()=>nativeReads,calls:()=>findCalls};
 }
 const a=setup();assert.equal(preparePdf2htmlEx(a),true);assert.equal(preparePdf2htmlEx(a),false);
 a.viewer.find_pages();assert.equal(a.reads(),1);assert.equal(a.calls(),1);assert.equal(a.viewer.pages.length,606);
 assert.equal(a.viewer.container,a.container);assert.equal(Object.getPrototypeOf(a.viewer.pages[605]),a.prototype);
 assert.equal(a.viewer.page_map[17],16);assert.deepEqual(a.viewer.pages[16].ctm,[1,0,0,1,17,0]);
 assert.deepEqual(a.viewer.pages[16].ictm,[1,-0,-0,1,-17,0]);assert.equal(a.viewer.pages[16].original_scale,600/601);
 a.viewer.render();a.viewer.schedule_render();assert.equal(a.viewer.render_timer,null);
 for(const bad of ['missing-size','bad-matrix','wrong-id']){
  const b=setup(3),find=b.viewer.find_pages,render=b.viewer.render;
  if(bad==='missing-size')b.frames[2].getAttribute=n=>n==='data-page-no'?'3':null;
  if(bad==='bad-matrix')b.frames[2].querySelector=s=>s==='.pc'?{}:{getAttribute(){return '{"ctm":[0,0,0,0,0,0]}';}};
  if(bad==='wrong-id')b.frames[2].id='pf9';
  assert.equal(preparePdf2htmlEx(b),false);assert.equal(b.viewer.find_pages,find);assert.equal(b.viewer.render,render);
 }
 console.log('early-runtime: 606-page startup, private methods, CTM, idempotence and fail-closed metadata passed');
})().catch(e=>{console.error(e);process.exitCode=1});
