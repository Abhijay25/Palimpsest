(() => {
 'use strict';
 const $=id=>document.getElementById(id), M=window.SkylineModel, DAY=M.DAY;
 const names={en:'English',fi:'Suomi',sv:'Svenska'};
 const labels={coverage:'Additional context',framing:'Different framing',contradiction:'Possible contradiction'};
 const colors={coverage:'#edc27d',framing:'#df793f',contradiction:'#ad3832'};
 const initial=new URLSearchParams(location.search);
 const state={languages:[],data:null,matrix:null,from:0,to:0,kind:'all',pair:'all',sort:'controversial',changed:false,
  stamp:null,group:null,focus:null,current:'en',matches:null,search:'',request:0,searchRequest:0,load:0,poll:null,rows:[],bins:[]};
 const fmt=v=>new Date(v).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
 const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const svg=(tag,attrs={},text)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;return n;};
 const mobile=()=>innerWidth<=700, columns=()=>mobile()?7:12;
 const rowHeight=()=>mobile()?54:44;
 const query=()=>{const q=new URLSearchParams({topic:'Q134949'});state.languages.forEach(l=>q.append('languages',l));if(state.data)q.set('run',state.data.run);return q;};
 const bounds=()=>[M.floor(Date.parse(state.data.bounds[0]),'day'),M.next(M.floor(Date.parse(state.data.bounds[1]),'day'),'day')];
 const message=(text,error=false)=>{$('form-message').textContent=text;$('form-message').classList.toggle('error',error);};
 async function json(url,options={}){const r=await fetch(url,{signal:AbortSignal.timeout(60000),...options}),d=await r.json();if(!r.ok)throw Error(d.error||'Stored results are unavailable.');return d;}
 function save(){
  if(!state.data)return;const q=query();
  for(const [k,v] of Object.entries({current:state.current,from:new Date(state.from).toISOString(),to:new Date(state.to).toISOString(),kind:state.kind,pair:state.pair,sort:state.sort}))q.set(k,v);
  if(state.changed)q.set('changed','1');if(state.stamp)q.set('observation',state.stamp);if(state.group)q.set('question',state.group);
  if(state.focus)q.set('focus',state.focus);if(state.search)q.set('q',state.search);if($('heatmap-scroll').scrollTop)q.set('scroll',String(Math.round($('heatmap-scroll').scrollTop)));
  history.replaceState(null,'','/explore?'+q);
 }
 function languageOptions(){const q=$('language-search').value.toLowerCase();$('language-options').replaceChildren();for(const [lang,name]of Object.entries(names)){if(state.languages.includes(lang)||!(name+' '+({fi:'Finnish',sv:'Swedish'}[lang]||'')).toLowerCase().includes(q))continue;const b=el('button','',name);b.type='button';b.onclick=()=>{state.languages.push(lang);refreshLanguages();$('language-menu').hidden=true;$('add-language').setAttribute('aria-expanded','false');};$('language-options').append(b);}}
 function refreshLanguages(){
  $('language-placeholder').hidden=state.languages.length>0;$('language-pills').replaceChildren();
  for(const lang of state.languages){const p=el('span','language-pill',names[lang]),b=el('button','','×');b.type='button';b.setAttribute('aria-label','Remove '+names[lang]);b.onclick=()=>{state.languages=state.languages.filter(l=>l!==lang);refreshLanguages();};p.append(b);$('language-pills').append(p);}languageOptions();
 }
 function topicOptions(){const q=$('topic-search').value.toLowerCase();$('topic-results').replaceChildren();if(!q||['winter war','talvisota','vinterkriget','q134949'].some(t=>t.includes(q))||q.includes('/wiki/')){const b=el('button','','Winter War');b.type='button';b.setAttribute('role','option');b.onclick=()=>{$('topic-search').value='Winter War';$('topic-results').hidden=true;$('add-language').focus();};$('topic-results').append(b);}else $('topic-results').append(el('p','search-empty','This iteration includes Winter War.'));$('topic-results').hidden=false;}
 async function start(restore=false){
  const title=$('topic-search').value.trim().toLowerCase();if(!['winter war','q134949','talvisota','vinterkriget'].includes(title)&&!['winter_war','talvisota','vinterkriget'].some(t=>title.endsWith('/wiki/'+t))){message('Choose Winter War for this comparison.',true);return;}
  if(state.languages.length<2){message('Choose at least two language editions.',true);return;}
  const generation=++state.load,button=$('query-form').querySelector('[type=submit]');button.disabled=true;message('Reading prepared comparisons…');clearTimeout(state.poll);
  try{
   state.data=null;state.matrix=null;const q=query();if(restore&&initial.get('run'))q.set('run',initial.get('run'));
   const data=await json('/explore/api/skyline?'+q);if(generation!==state.load)return;state.data=data;
   const [a,b]=bounds();state.from=restore&&Number.isFinite(Date.parse(initial.get('from')))?Math.max(a,Date.parse(initial.get('from'))):a;state.to=restore&&Number.isFinite(Date.parse(initial.get('to')))?Math.min(b,Date.parse(initial.get('to'))):b;
   if(state.to-state.from<DAY){state.from=a;state.to=b;}
   state.kind=restore&&M.kinds.includes(initial.get('kind'))?initial.get('kind'):'all';state.pair=restore?initial.get('pair')||'all':'all';state.sort=restore&&['controversial','alphabetical','recent','relevance'].includes(initial.get('sort'))?initial.get('sort'):'controversial';state.changed=restore&&initial.get('changed')==='1';
   state.stamp=restore?initial.get('observation'):null;state.group=restore?initial.get('question'):null;state.focus=restore?(initial.get('focus')||(!state.group?state.stamp:null)):null;
   state.current=state.languages.includes(initial.get('current'))?initial.get('current'):(state.languages.includes('en')?'en':state.languages[0]);state.search=restore?initial.get('q')||'':'';state.matches=null;
   $('pair-filter').replaceChildren(el('option','','All pairs'));$('pair-filter').firstChild.value='all';
   const langs=[...state.languages].sort();for(let i=0;i<langs.length;i++)for(let j=i+1;j<langs.length;j++){const name=langs[i].toUpperCase()+'–'+langs[j].toUpperCase(),option=el('option','',name);option.value=name;$('pair-filter').append(option);}if(![...$('pair-filter').options].some(o=>o.value===state.pair))state.pair='all';
   $('kind-filter').value=state.kind;$('pair-filter').value=state.pair;$('question-sort').value=state.sort;$('changed-only').checked=state.changed;$('question-query').value=state.search;
   document.body.classList.add('exploring');$('prompt-screen').hidden=true;$('skyline-screen').hidden=false;$('edit-query').hidden=false;$('query-summary').textContent='Winter War';$('query-languages').textContent=state.languages.map(l=>l.toUpperCase()).join(' · ');message('');render();
   $('heatmap-body').replaceChildren(el('p','matrix-loading','Loading stored questions and observations…'));
   state.matrix=await json('/explore/api/matrix?'+query());if(generation!==state.load)return;
   if(state.search)await search(false);render();$('heatmap-scroll').scrollTop=restore?Number(initial.get('scroll'))||0:0;drawRows();
   if(state.group&&state.stamp)openCell(state.group,state.stamp,false);poll();
  }catch(error){message(error.message,true);$('question-count').textContent='Stored questions unavailable. Use Full history or reload to retry.';}finally{button.disabled=false;}
 }
 function render(){
  if(!state.data)return;const progress=state.data.progress||{};
  $('skyline-subtitle').textContent=state.languages.map(l=>names[l]).join(' · ')+' · historical language differences';$('run-warning').textContent=state.data.warning;
  $('skyline-status').textContent=progress.stage==='ready'?'Real stored results · model judgments need review':'Preparation incomplete · stored observations only';
  const [a,b]=bounds();$('window-label').textContent=fmt(state.from)+' — '+fmt(state.to-1);$('period-previous').disabled=state.from<=a;$('period-next').disabled=state.to>=b;
  $('skyline-zoom-in').disabled=state.to-state.from<=DAY;$('skyline-zoom-out').disabled=state.from<=a&&state.to>=b;
  for(const [id,value]of [['window-start',state.from],['window-end',state.to]]){$(id).step=DAY/(b-a)*100;$(id).value=(value-a)/(b-a)*100;}
  $('brush-selection').style.left=(state.from-a)/(b-a)*100+'%';$('brush-selection').style.right=(b-state.to)/(b-a)*100+'%';
  const model=M.bins(state.data.observations,state.from,state.to,columns());state.bins=model.bins;state.unit=model.unit;
  $('resolution-label').textContent=({year:'Yearly',month:'Monthly',week:'Weekly',day:'Daily'}[model.unit])+' observations';
  document.querySelectorAll('[data-unit]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.unit===model.unit)));
  drawOverview();updateRows();save();
 }
 function periodLabel(bin){const d=new Date(bin.start);return state.unit==='year'?String(d.getUTCFullYear()):d.toLocaleDateString('en-GB',state.unit==='month'?{month:'short',year:'2-digit',timeZone:'UTC'}:{day:'numeric',month:'short',timeZone:'UTC'});}
 let clickTimer;
 function periodEvents(node,bin){node.onclick=()=>{clearTimeout(clickTimer);clickTimer=setTimeout(()=>focusPeriod(bin),220);};node.ondblclick=e=>{e.preventDefault();clearTimeout(clickTimer);drill(bin);};}
 function drawOverview(){
  const width=$('timeline-chart').clientWidth||800,height=84,max=Math.max(1,...state.bins.map(b=>b.total||0));
  const chart=svg('svg',{viewBox:`0 0 ${width} ${height}`,width,height,role:'group','aria-label':'All distinct questions in each sampled period'});
  state.bins.forEach((bin,i)=>{const cell=width/state.bins.length,w=cell*.65,x=i*cell+(cell-w)/2;const g=svg('g',{role:'button',tabindex:'0','aria-label':bin.observation?fmt(bin.observation.stamp)+': '+bin.total+' questions':periodLabel(bin)+': not assessed',class:'overview-column'+(state.focus===bin.observation?.stamp?' selected':'')});
   g.append(svg('rect',{x:i*cell,y:0,width:cell,height,fill:'transparent'}));let y=64;
   if(bin.observation){for(const kind of M.kinds){const h=bin.counts[kind]/max*46;y-=h;if(h)g.append(svg('rect',{x,y,width:w,height:h,fill:colors[kind]}));}g.append(svg('text',{x:x+w/2,y:y-5,'text-anchor':'middle'},String(bin.total)));}
   else g.append(svg('line',{x1:x,y1:63,x2:x+w,y2:63,class:'overview-unknown'}));
   g.append(svg('text',{x:x+w/2,y:80,'text-anchor':'middle'},periodLabel(bin)));periodEvents(g,bin);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();focusPeriod(bin);}if(e.key==='ArrowDown'){e.preventDefault();drill(bin);}};
   g.onpointerenter=()=>{g.append(svg('title',{},bin.observation?fmt(bin.observation.stamp)+' · '+M.kinds.map(k=>labels[k]+': '+bin.counts[k]).join(' · '):'No assessment in this period'));};chart.append(g);
  });$('timeline-chart').replaceChildren(chart);
 }
 function updateRows(){
  const head=$('heatmap-head');head.replaceChildren(el('span','heatmap-label-heading','Semantic questions'));
  for(const bin of state.bins){const b=el('button','date-heading',periodLabel(bin));b.type='button';b.title=bin.observation?'Latest assessed: '+fmt(bin.observation.stamp):'No observation in this period';b.setAttribute('aria-label',b.title+'. Select to focus; double-click to zoom.');periodEvents(b,bin);head.append(b);}
  $('heatmap-scroll').style.setProperty('--columns',state.bins.length);
  if(!state.matrix)return;
  const all=M.visibleRows(state.matrix.rows,state.bins,{});let rows=M.visibleRows(state.matrix.rows,state.bins,{kind:state.kind,pair:state.pair,changed:state.changed,matches:state.matches,sort:state.sort});
  if(state.focus)rows=rows.filter(r=>r.visibleCells.some(c=>c?.stamp===state.focus));state.rows=rows;
  $('question-count').textContent=rows.length+' of '+all.length+' questions in displayed observations · '+state.matrix.rows.length+' across full history';
  $('clear-observation').hidden=!state.focus;$('clear-observation').textContent=state.focus?'Clear '+fmt(state.focus)+' focus':'';
  $('heatmap-empty').hidden=rows.length>0;$('heatmap-empty').textContent=state.search?'No matching questions in these observations. Try another phrase, clear filters or widen the date range.':'No recorded questions match this view. Clear filters or widen the date range; missing findings do not prove agreement.';
  $('heatmap-body').style.height=rows.length*rowHeight()+'px';drawRows();
 }
 function drawRows(){
  if(!state.matrix)return;const active=document.activeElement,focused=active?.matches('.heat-cell')?{row:active.dataset.row,col:active.dataset.col}:null;
  const viewport=$('heatmap-scroll'),body=$('heatmap-body'),height=rowHeight(),start=Math.max(0,Math.floor((viewport.scrollTop-42)/height)-3),end=Math.min(state.rows.length,start+Math.ceil(viewport.clientHeight/height)+7);
  const fragment=document.createDocumentFragment();
  for(let index=start;index<end;index++){
   const row=state.rows[index],node=el('div','heatmap-row'+(row.id===state.group?' selected':''));node.style.top=index*height+'px';node.style.height=height+'px';node.dataset.row=String(index);
   const label=el('button','heatmap-row-label');label.type='button';label.title=row.title;label.append(el('span','row-number',String(index+1).padStart(2,'0')),el('span','row-title',row.title));
   label.onclick=()=>{const c=row.visibleCells.findLast(Boolean);if(c)openCell(row.id,c.stamp,true,c.kind);};node.append(label);
   row.visibleCells.forEach((cell,col)=>{
    const bin=state.bins[col],button=el('button','heat-cell '+(cell?cell.kind:bin.observation?'absent':'unknown')+(row.id===state.group&&cell?.stamp===state.stamp?' active':''));button.type='button';button.dataset.col=String(col);button.dataset.row=String(index);
    const description=cell?labels[cell.kind]+' · '+fmt(cell.stamp)+' · '+cell.supporting_pairs.join(', '):bin.observation?'No stored finding at '+fmt(bin.observation.stamp)+'. This does not establish agreement.':'Not assessed in '+periodLabel(bin)+'.';
    button.setAttribute('aria-label',row.title+'. '+description);button.title=description;button.tabIndex=col===0?0:-1;button.setAttribute('aria-pressed',String(row.id===state.group&&cell?.stamp===state.stamp));
    if(cell)button.append(el('span','cell-ink'));else if(bin.observation)button.append(el('span','absence-dot','·'));
    button.onclick=()=>cell?openCell(row.id,cell.stamp,true,cell.kind):explainMissing(bin,row);button.onkeydown=e=>cellKey(e,index,col);node.append(button);
   });fragment.append(node);
  }body.replaceChildren(fragment);if(focused)body.querySelector(`button.heat-cell[data-row="${focused.row}"][data-col="${focused.col}"]`)?.focus({preventScroll:true});
 }
 function cellKey(event,row,col){
  const moves={ArrowLeft:[0,-1],ArrowRight:[0,1],ArrowUp:[-1,0],ArrowDown:[1,0]},move=moves[event.key];if(!move)return;event.preventDefault();
  const nextRow=Math.max(0,Math.min(state.rows.length-1,row+move[0])),nextCol=Math.max(0,Math.min(state.bins.length-1,col+move[1])),viewport=$('heatmap-scroll'),top=nextRow*rowHeight();
  if(top<viewport.scrollTop)viewport.scrollTop=top;else if(top+rowHeight()>viewport.scrollTop+viewport.clientHeight-42)viewport.scrollTop=top-viewport.clientHeight+rowHeight()+42;
  drawRows();const target=$('heatmap-body').querySelector(`button.heat-cell[data-row="${nextRow}"][data-col="${nextCol}"]`);target?.focus({preventScroll:true});
 }
 function panel(open){$('question-panel').hidden=!open;document.body.classList.toggle('questions-open',open);if(!open)$('tracker-action').hidden=true;}
 function closePanel(){state.request++;state.group=null;state.stamp=null;panel(false);drawRows();save();}
 function explainMissing(bin,row){state.request++;state.group=null;state.stamp=null;panel(true);$('tracker-action').hidden=true;$('questions-heading').textContent=bin.observation?'No recorded finding':'Not assessed';$('evidence-content').replaceChildren(el('p','evidence-note',row.title),el('p','evidence-note',bin.observation?'There is no stored finding for this question at '+fmt(bin.observation.stamp)+'. The pipeline stores actionable differences, so absence is not proof of agreement or resolution.':'There was no assessment in this period. Adjacent colored cells do not establish what happened in this gap.'));save();}
 async function openCell(group,stamp,focus=false,kind=null){
  state.group=group;state.stamp=stamp;const generation=++state.request;panel(true);$('tracker-action').hidden=true;$('questions-heading').textContent='Historical evidence';$('evidence-content').replaceChildren(el('p','matrix-loading','Loading exact source evidence…'));drawRows();save();
  const q=query();q.set('group',group);q.set('stamp',stamp);q.set('current',state.current);q.set('back',location.search.slice(1));q.set('pair',state.pair);q.set('kind',kind||state.kind);
  try{const data=await json('/explore/api/cell?'+q);if(generation!==state.request)return;$('questions-heading').textContent=data.title;const content=$('evidence-content');content.replaceChildren(el('span','evidence-kind '+data.kind,data.label),el('p','evidence-meta',fmt(data.stamp)+' · '+data.destination));
   for(const source of data.evidence){const block=el('section','source-preview');block.append(el('h3','',source.lang.toUpperCase()+' · Original'));
    const quote=el('p','source-quote');quote.lang=source.lang;quote.innerHTML=source.quote_html;block.append(quote);
    const url=new URL(source.url);if(url.protocol==='https:'&&url.hostname===source.lang+'.wikipedia.org'){const link=el('a','revision-link','Revision '+source.revision+' · '+fmt(source.stamp));link.href=url.href;link.target='_blank';link.rel='noopener';block.append(link);}
    if(source.translation){const translation=el('p','source-translation',source.translation);block.append(el('small','','Cached machine translation · verify against original'),translation);}else if(source.lang!=='en')block.append(el('p','evidence-note','Translation is available in the article tracker.'));
    content.append(block);
   }
   const link=$('tracker-action');link.href=data.href;link.textContent='Review '+data.destination+' article evidence →';link.hidden=false;content.append(el('p','evidence-note',data.occurrences+' supporting source occurrence'+(data.occurrences===1?'':'s')+' · model judgment, not a verified error'));
   if(focus)$('questions-heading').focus({preventScroll:true});
  }catch(error){if(generation===state.request)$('evidence-content').replaceChildren(el('p','evidence-note',error.message));}
 }
 function focusPeriod(bin){closePanel();state.focus=bin.observation?.stamp||null;$('heatmap-scroll').scrollTop=0;render();if(!bin.observation){panel(true);$('questions-heading').textContent='Not assessed';$('evidence-content').replaceChildren(el('p','evidence-note','No observation in '+periodLabel(bin)+'. Zooming reveals available samples; it cannot fill unassessed dates.'));}}
 function clearSelection(){state.focus=null;closePanel();$('heatmap-scroll').scrollTop=0;render();}
 function drill(bin){const [a,b]=bounds();state.from=Math.max(a,bin.start);state.to=Math.min(b,bin.end);clearSelection();}
 function scale(unit){const [a,b]=bounds(),anchor=state.stamp?Date.parse(state.stamp):state.focus?Date.parse(state.focus):Date.parse(state.data.observations.filter(o=>o.state!=='unknown'&&Date.parse(o.stamp)>=state.from&&Date.parse(o.stamp)<state.to).at(-1)?.stamp||new Date(state.to-1).toISOString());[state.from,state.to]=M.windowForUnit(anchor,unit,columns(),a,b);clearSelection();}
 function zoom(factor,anchor){const [a,b]=bounds(),span=Math.max(DAY,Math.min(b-a,Math.round((state.to-state.from)*factor/DAY)*DAY)),center=anchor||(state.stamp?Date.parse(state.stamp):(state.from+state.to)/2);state.from=Math.max(a,Math.min(b-span,M.floor(center-span/2,'day')));state.to=Math.min(b,state.from+span);clearSelection();}
 function pan(direction){const [a,b]=bounds(),span=state.to-state.from;state.from=Math.max(a,Math.min(b-span,state.from+direction*span));state.to=Math.min(b,state.from+span);clearSelection();}
 async function search(changeSort=true){
  const text=$('question-query').value.trim(),generation=++state.searchRequest;state.search=text;
  if(!text){state.matches=null;$('search-submit').disabled=false;$('search-status').textContent='';if(state.sort==='relevance'){state.sort='controversial';$('question-sort').value=state.sort;}updateRows();save();return;}
  if(text.length<2){$('search-status').textContent='Enter at least two characters.';return;}
  $('search-submit').disabled=true;$('search-status').textContent='Searching keywords + local semantic vectors…';
  try{const result=await json('/explore/api/search?'+query(),{method:'POST',headers:{'Content-Type':'application/json','X-Review-Token':document.querySelector('meta[name=review-token]').content},body:JSON.stringify({query:text})});if(generation!==state.searchRequest)return;
   state.matches=result.matches;if(changeSort){state.sort='relevance';$('question-sort').value='relevance';}$('search-status').textContent=result.warning||'Keywords + up to 40 nearest semantic matches · local model';$('heatmap-scroll').scrollTop=0;updateRows();save();
  }catch(error){if(generation===state.searchRequest){state.matches=[];$('search-status').textContent=error.message;updateRows();}}finally{if(generation===state.searchRequest)$('search-submit').disabled=false;}
 }
 function poll(){clearTimeout(state.poll);if(!state.data||['ready','partial'].includes(state.data.progress?.stage))return;state.poll=setTimeout(async()=>{try{state.data=await json('/explore/api/skyline?'+query());state.matrix=await json('/explore/api/matrix?'+query());render();}catch(error){}poll();},5000);}
 $('query-form').onsubmit=e=>{e.preventDefault();start();};$('topic-search').oninput=topicOptions;$('topic-search').onfocus=topicOptions;$('topic-toggle').onclick=topicOptions;
 $('topic-search').onkeydown=e=>{if(e.key==='Escape')$('topic-results').hidden=true;if(e.key==='ArrowDown'){e.preventDefault();$('topic-results').querySelector('button')?.focus();}};
 $('add-language').onclick=()=>{$('language-menu').hidden=!$('language-menu').hidden;$('add-language').setAttribute('aria-expanded',String(!$('language-menu').hidden));if(!$('language-menu').hidden){$('language-search').value='';languageOptions();$('language-search').focus();}};$('language-search').oninput=languageOptions;
 document.querySelector('[data-example=Q134949]').onclick=()=>{state.languages=['en','fi','sv'];refreshLanguages();$('topic-search').value='Winter War';start();};
 document.addEventListener('click',e=>{if(!e.target.closest('.topic-field'))$('topic-results').hidden=true;if(!e.target.closest('.languages-field'))$('language-menu').hidden=true;});
 $('edit-query').onclick=()=>{++state.load;++state.searchRequest;clearTimeout(state.poll);closePanel();state.data=null;state.matrix=null;document.body.classList.remove('exploring');$('prompt-screen').hidden=false;$('skyline-screen').hidden=true;$('edit-query').hidden=true;history.replaceState(null,'','/explore');message('');$('topic-search').focus();};
 for(const [id,key]of [['kind-filter','kind'],['pair-filter','pair'],['question-sort','sort']])$(id).onchange=e=>{state[key]=e.target.value;closePanel();$('heatmap-scroll').scrollTop=0;updateRows();save();};
 $('changed-only').onchange=e=>{state.changed=e.target.checked;closePanel();$('heatmap-scroll').scrollTop=0;updateRows();save();};
 $('question-search').onsubmit=e=>{e.preventDefault();search();};$('question-query').oninput=e=>{if(!e.target.value)search();};
 $('ranking-info').onclick=()=>{$('ranking-note').hidden=!$('ranking-note').hidden;};$('close-questions').onclick=closePanel;$('clear-observation').onclick=()=>{state.focus=null;render();};
 document.querySelectorAll('[data-unit]').forEach(b=>b.onclick=()=>scale(b.dataset.unit));$('period-previous').onclick=()=>pan(-1);$('period-next').onclick=()=>pan(1);
 $('skyline-zoom-in').onclick=()=>zoom(.4);$('skyline-zoom-out').onclick=()=>zoom(2.5);$('skyline-reset').onclick=()=>{[state.from,state.to]=bounds();clearSelection();};
 ['window-start','window-end'].forEach((id,index)=>$(id).oninput=e=>{const [a,b]=bounds(),value=M.floor(a+Number(e.target.value)/100*(b-a),'day');if(index===0)state.from=Math.max(a,Math.min(value,state.to-DAY));else state.to=Math.min(b,Math.max(value,state.from+DAY));clearSelection();});
 let scrollFrame; $('heatmap-scroll').onscroll=()=>{cancelAnimationFrame(scrollFrame);scrollFrame=requestAnimationFrame(()=>{drawRows();save();});};
 $('heatmap-scroll').onkeydown=e=>{if(e.target.id==='heatmap-scroll'&&['+','=','-'].includes(e.key)){e.preventDefault();zoom(e.key==='-'?2.5:.4);}};
 $('guide-toggle').onclick=()=>{$('reading-guide').hidden=!$('reading-guide').hidden;$('guide-toggle').setAttribute('aria-expanded',String(!$('reading-guide').hidden));};$('close-guide').onclick=()=>{$('reading-guide').hidden=true;$('guide-toggle').setAttribute('aria-expanded','false');};
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('reading-guide').hidden=true;if(!$('question-panel').hidden)closePanel();}});
 let lastWidth=innerWidth;new ResizeObserver(()=>{if(state.data&&Math.abs(lastWidth-innerWidth)>5){lastWidth=innerWidth;render();}else if(state.data)drawOverview();}).observe($('timeline-chart'));
 refreshLanguages();if(initial.get('topic')==='Q134949'){state.languages=[...new Set(initial.getAll('languages'))].filter(l=>names[l]);if(state.languages.length<2)state.languages=['en','fi','sv'];refreshLanguages();$('topic-search').value='Winter War';start(true);}
})();
