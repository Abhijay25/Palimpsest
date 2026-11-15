/* Explicit native request preview + durable jobs. Polling only reads status. */
(function () {
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const names={revision:'Revision edit scan',page:'Page consistency check',language:'Language comparison'};
 const active=new Set(['queued','running','awaiting_index']);
 async function mount({host,call,url,edition,canScan,revision}) {
  if(!host)return;
  host.innerHTML='<h3>Request a background check</h3><p>Choose exact source revisions, review the provider and server allowance, then queue a request. You can leave this page while it runs.</p>'+
   '<form class="native-job-form"><label>Check<select name="kind"><option value="revision">Revision edit scan</option><option value="page">Page consistency check</option><option value="language">Language comparison</option></select></label>'+
   '<fieldset class="native-job-languages" hidden><legend>Compare editions</legend>'+['en','fi','sv'].map(lang=>'<label><input type="checkbox" name="languages" value="'+lang+'" checked'+(lang===edition?' disabled':'')+'>'+lang.toUpperCase()+'</label>').join('')+'</fieldset>'+
   '<button type="submit"'+(!canScan?' disabled':'')+'>Preview request</button></form><p class="native-job-policy" role="status">Reading server policy…</p>'+
   (!canScan?'<p>Sign in with native scan permission to request work.</p>':'')+
   '<div class="native-job-preview"></div><h3>Background requests for this article</h3><p class="native-job-status" role="status"></p><div class="native-job-list"></div><button class="native-job-refresh">Refresh status</button>';
  const form=host.querySelector('form'),preview=host.querySelector('.native-job-preview'),status=host.querySelector('.native-job-status');
  let currentPolicy=null,timer=null,busy=false;
  const selectedLanguages=()=>[...form.querySelectorAll('[name="languages"]:checked')].map(n=>n.value);
  form.elements.kind.onchange=()=>{host.querySelector('fieldset').hidden=form.elements.kind.value!=='language';preview.replaceChildren();};
  form.onchange=()=>preview.replaceChildren();
  document.getElementById('flags-revision')?.addEventListener('change',()=>preview.replaceChildren());
  function sourceRows(sources){return '<ul>'+sources.map(s=>'<li>'+esc(s.lang.toUpperCase())+' · <a target="_blank" rel="noopener" href="https://'+esc(s.lang)+'.wikipedia.org/w/index.php?oldid='+Number(s.revision_id)+'">source '+Number(s.revision_id)+'</a> · '+esc(s.timestamp)+(s.parent_sha256?' · exact parent '+Number(s.parent_id):'')+'<details><summary>Source integrity</summary><p>Text SHA-256 <code>'+esc(s.sha256)+'</code>'+(s.parent_sha256?'<br>Parent SHA-256 <code>'+esc(s.parent_sha256)+'</code>':'')+'</p></details></li>').join('')+'</ul>';}
  async function policy(){try{currentPolicy=await call('jobpolicy',{});host.querySelector('.native-job-policy').textContent=(currentPolicy.enabled?'Server policy: '+currentPolicy.authorization:'New on-demand inference is disabled by server policy.')+' '+currentPolicy.notice;}catch(e){host.querySelector('.native-job-policy').textContent=e.message;}}
  async function prepare(previous=null,prior=null){
   if(busy)return;busy=true;form.querySelector('button').disabled=true;preview.innerHTML='<p role="status">Preparing exact source identities. No provider request has been made.</p>';
   try{
    const kind=prior?.kind||form.elements.kind.value,own=prior?.configuration.sources.find(s=>s.lang===edition);
    const selection={revision:String(own?.revision_id||revision()),languages:prior?.configuration.sources.map(s=>s.lang)||selectedLanguages()};
    const {plan}=await call('jobplan',selection,{mode:kind}),c=plan.configuration,engine=c.engine,allowance=currentPolicy?.engines[kind];
    preview.innerHTML='<h4>'+(previous?'Fresh rescan':'Request preview')+'</h4>'+sourceRows(c.sources)+'<p>Provider: '+esc(engine.provider||'unconfigured')+' · model: '+esc(engine.model||'unconfigured')+' · prompt: '+esc(engine.prompt_version||'unconfigured')+' · policy: '+esc(c.policy_version)+'</p>'+
     '<p>'+esc(plan.message)+(allowance?.max_provider_calls?' Provider-call allowance for this check type: '+Number(allowance.max_provider_calls)+'.':'')+(currentPolicy?.max_provider_calls?' Total allowance across check types: '+Number(currentPolicy.max_provider_calls)+'.':'')+' Failed or unresolved reservations count toward these allowances.</p>'+
     (kind==='language'?'<p>This compares these exact historical snapshots. It does not prepare the article’s entire history. Retrieval misses do not prove whole-article absence.</p>':'')+
     '<p>Successful compatible results are reused. Failed, partial or uncertain attempts are not silently repeated.'+(previous?' This explicitly requests a new assessment after the named successful job.':'')+'</p>'+
     '<button class="native-job-enqueue"'+(!plan.allowed?' disabled':'')+'>'+(previous?'Queue fresh rescan':'Queue this request')+'</button> <button class="native-job-cancel">Cancel preview</button><p class="native-job-enqueue-status" role="status"></p>';
    preview.querySelector('.native-job-cancel').onclick=()=>preview.replaceChildren();
    preview.querySelector('.native-job-enqueue').onclick=async event=>{
     event.target.disabled=true;const output=preview.querySelector('.native-job-enqueue-status');
     try{const {job}=await call('enqueue',{plan:plan.id,...(previous?{previous}:{})});output.textContent='Request '+job.id.slice(0,12)+' · '+job.status+'. This job is durable; leaving the page does not cancel it.';await refresh();}
     catch(e){output.textContent=e.message+' Repeating this button uses the same job identity.';event.target.disabled=false;}
    };
   }catch(e){preview.replaceChildren();const p=document.createElement('p');p.setAttribute('role','alert');p.textContent=e.message;preview.append(p);}
   finally{busy=false;form.querySelector('button').disabled=!canScan;}
  }
  async function refresh(){
   clearTimeout(timer);
   try{
    const data=await call('jobs',{}),list=host.querySelector('.native-job-list');
    status.textContent=data.jobs.length?'Latest '+data.jobs.length+' requests. Status refreshes while work is active.':'No background requests have been made for this article.';
    list.innerHTML=data.jobs.map(j=>'<article class="native-job"><h4>'+esc(names[j.kind]||j.kind)+' · '+esc(j.status.replace(/_/g,' '))+'</h4><p>Request '+esc(j.id.slice(0,12))+' · updated '+esc(j.updated)+' · '+esc(j.progress.stage||j.status)+'</p>'+
     (j.progress.provider_calls!==undefined?'<p>'+Number(j.progress.provider_calls)+' provider calls reserved</p>':'')+
     (j.result?.findings!==undefined?'<p>'+Number(j.result.findings)+' findings'+(j.result.partial?' · partial assessment; unassessed work remains unknown':' · successful assessment')+' · <a href="'+esc(url({checks:null,issue:null,observation:null,occurrence:null,stamp:null,group:null,source:null,view:null,kind:null,kinds:null,q:null,review:null,scope:null,from:null,to:null,page:1,languages:j.configuration.sources.map(s=>s.lang),run:j.result.run||null,assessment:j.result.assessment||null,origin:j.kind==='language'?'language':'flags'}))+'">View this result’s Issues</a></p>':'')+
     (j.error?'<p role="alert">'+esc(j.error)+'</p>':'')+
     '<details><summary>Exact request and engine</summary>'+sourceRows(j.configuration.sources)+'<p>'+esc(j.configuration.engine.provider)+' · '+esc(j.configuration.engine.model)+' · policy '+esc(j.configuration.policy_version)+'</p></details>'+
     (j.status==='completed'&&canScan&&currentPolicy?.engines[j.kind]?.allow_rescan?'<button data-rescan="'+esc(j.id)+'">Preview fresh rescan</button>':'')+'</article>').join('');
    for(const button of list.querySelectorAll('[data-rescan]'))button.onclick=()=>prepare(button.dataset.rescan,data.jobs.find(j=>j.id===button.dataset.rescan));
    if(data.jobs.some(j=>active.has(j.status)))timer=setTimeout(refresh,4000);
   }catch(e){status.textContent=e.message+' Use Refresh status to reconnect; no work was restarted.';}
  }
  form.onsubmit=e=>{e.preventDefault();prepare();};
  host.querySelector('.native-job-refresh').onclick=refresh;
  await policy();await refresh();
 }
 window.PalimpsestJobs={mount};
}());
