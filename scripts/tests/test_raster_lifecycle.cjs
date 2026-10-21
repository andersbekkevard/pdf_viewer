'use strict';
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
async function main(){
 const src=fs.readFileSync(path.resolve(__dirname,'../../assets/overlay-document.js'),'utf8');
 const {createDocumentModel}=await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'));
 let observer;let writes=0;let pageQueries=0;
 function image(source){const attr={'data-pdf2html-src':source};const listeners={};return {complete:false,naturalWidth:0,getAttribute:k=>attr[k]??null,hasAttribute:k=>k in attr,setAttribute(k,v){attr[k]=v;writes++;},removeAttribute(k){delete attr[k];writes++;},addEventListener:(k,fn)=>listeners[k]=fn,finish(ok=true){this.complete=true;this.naturalWidth=ok?1200:0;listeners[ok?'load':'error']();}};}
 const frames=Array.from({length:606},(_,i)=>({id:'pf'+(i+1).toString(16),images:[image('page-images/'+(i+1)+'.png')],dataset:{},querySelectorAll(){return this.images;}}));
 frames[0].images.push(image('page-images/first-extra.png'));
 const root={querySelectorAll(){pageQueries++;return frames;}};
 const document={getElementById:()=>root};
 const window={IntersectionObserver:class{constructor(callback,options){observer={callback,options,observed:[]};}observe(p){observer.observed.push(p);}}};
 const model=createDocumentModel({document,window,requestAnimationFrame(){throw Error('unexpected frame loop');}});
 model.mountRasterLifecycle();
 const notify=(enter,exit=[])=>observer.callback([...exit.map(target=>({target,isIntersecting:false})),...enter.map(target=>({target,isIntersecting:true}))]);
 assert.equal(observer.observed.length,606);
 assert.equal(model.totalPages(),606);assert.equal(pageQueries,1);
 notify(frames.slice(0,5));assert.equal(frames[0].dataset.pdf2htmlRasterState,'loading');
 frames[0].images[0].finish();assert.equal(frames[0].dataset.pdf2htmlRasterState,'loading','all rasters must finish');
 frames[0].images[1].finish();assert.equal(frames[0].dataset.pdf2htmlRasterState,'ready');
 const warmedWrites=writes;for(let i=0;i<60;i++)notify(frames.slice(0,5));assert.equal(writes,warmedWrites,'unchanged proximity must not reload sources');
 notify(frames.slice(500,505),frames.slice(0,5));assert.equal(frames[0].dataset.pdf2htmlRasterState,'unloaded');
 assert(frames.slice(0,5).every(p=>p.images.every(i=>!i.hasAttribute('src'))));
 frames[0].images[0].finish();assert.equal(frames[0].dataset.pdf2htmlRasterState,'unloaded','late completion cannot revive an exited page');
 frames[500].images[0].finish(false);assert.equal(frames[500].dataset.pdf2htmlRasterState,'error');
 notify([],frames.slice(500,505));notify([frames[500]]);assert(frames[500].images[0].hasAttribute('src'),'re-entry retries a failed raster');
 frames[500].images[0].finish();assert.equal(frames[500].dataset.pdf2htmlRasterState,'ready');
 console.log('PASS: static page count, bounded entry/exit, unchanged repeated proximity, aggregate readiness, stale completion and failed-raster retry');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
