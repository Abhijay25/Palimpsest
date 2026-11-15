'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'static/issue-translations.js'),'utf8');
function fixture(text='',request=async()=>({text:'The border moved west.',cached:false})){
 const nodes=[],calls=[];function node(tag){const n={tag,children:[],textContent:'',hidden:false,disabled:false,append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},setAttribute(){}};nodes.push(n);return n;}
 const window={},document={createElement:node};vm.runInNewContext(code,{window,document,Error});const root=node('main');
 window.PalimpsestIssueTranslations.mount(root,[{key:'exact-source',lang:'sv',text}],async key=>{calls.push(key);return request();});
 return {root,nodes,calls,button:nodes.find(n=>n.tag==='button')};
}
(async()=>{
 const fresh=fixture();assert.equal(fresh.calls.length,0);assert.equal(fresh.button.textContent,'Translate SV into English');
 await fresh.button.onclick();assert.deepEqual(fresh.calls,['exact-source']);assert.equal(fresh.button.textContent,'Hide English translation');
 await fresh.button.onclick();await fresh.button.onclick();assert.equal(fresh.calls.length,1);
 const cached=fixture('Already saved');assert.equal(cached.calls.length,0);await cached.button.onclick();assert.equal(cached.calls.length,0);
 let release;const pending=fixture('',()=>new Promise(resolve=>{release=resolve;}));const first=pending.button.onclick();await pending.button.onclick();assert.equal(pending.calls.length,1);assert.equal(pending.button.disabled,true);release({text:'Done'});await first;assert.equal(pending.button.disabled,false);
 const failed=fixture('',async()=>{throw Error('Model unavailable');});await failed.button.onclick();assert.equal(failed.button.textContent,'Retry English translation');assert.equal(failed.button.disabled,false);assert(failed.nodes.some(n=>n.textContent==='Model unavailable'));
 console.log('Issue translation: lazy start, exact source, cached reads, request deduplication and retry passed.');
})();
