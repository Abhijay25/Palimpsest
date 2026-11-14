(()=>{
 'use strict';
 const $=selector=>document.querySelector(selector);
 const esc=value=>String(value||'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 const safeUrl=value=>/^https?:\/\//.test(String(value||''))?String(value):'';
 const labels={FACT:'Fact',FRAMING:'Wording',MOTIVE:'Motive',REMOVED_CONTEXT:'Removed context',HIDDEN_TEXT:'Hidden text',CITATION_DATE:'Citation date',CITED_PAGE:'Cited page',CHERRY_PICK:'Selective quote',OUT_OF_SYNC:'Out of sync'};
 const root=$('#flags-audit'),rail=$('.flags-rail__list'),summary=$('.flags-summary-bar'),tray=$('.flags-unanchored-tray');
 let flags=[],active=-1,hovered=-1,filter=new Set();
 const visibleFlags=()=>flags.filter(flag=>!filter.size||filter.has(flag.kind));
 const indexOf=flag=>flags.indexOf(flag);
 function card(flag,index){
  const item=document.createElement('li');item.className='flags-rail__item';item.dataset.flagId=flag.id;
  const article=document.createElement('article');article.className='flag-card flag-card--'+String(flag.kind||'').toLowerCase()+(flag.tier==='admin'?' flag-card--admin':'');article.dataset.flagId=flag.id;article.tabIndex=0;article.setAttribute('role','button');article.setAttribute('aria-expanded','false');
  article.innerHTML=`<div class="flag-card__meta"><span class="flag-card__pill">${esc(labels[flag.kind]||flag.kind)}</span><span class="flag-card__confidence">${flag.confidence?Math.round(flag.confidence*100)+'% confidence':''}</span></div><div class="flag-card__title">${esc(flag.title||labels[flag.kind]||'Flag')}</div><div class="flag-card__body"><p class="flag-card__reason">${esc(flag.reason)}</p>${(flag.evidence||[]).map(e=>`<blockquote class="flag-card__evidence">${esc(e.quote)}${safeUrl(e.url)?` <a href="${esc(safeUrl(e.url))}" target="_blank" rel="noopener">source</a>`:''}</blockquote>`).join('')}${flag.neutral_rewrite?`<p class="flag-card__suggestion-label">Suggested wording</p><div class="flag-card__suggestion">${esc(flag.neutral_rewrite)}</div>`:''}</div>`;
  article.addEventListener('mouseenter',()=>setHover(index,true));article.addEventListener('mouseleave',()=>setHover(index,false));
  article.addEventListener('click',()=>activate(index,true));article.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();activate(index,true);}});
  item.append(article);return item;
 }
 function syncHighlights(){
  const activeId=flags[active]?.id,hoveredId=flags[hovered]?.id;
  document.querySelectorAll('.diff-anchor').forEach(mark=>mark.classList.toggle('is-active',mark.dataset.flagId===activeId||mark.dataset.flagId===hoveredId));
  document.querySelectorAll('.flag-card').forEach(card=>card.classList.toggle('is-active',card.dataset.flagId===activeId||card.dataset.flagId===hoveredId));
 }
 function setHover(index,on){hovered=on?index:-1;syncHighlights();}
 function activate(index,scroll){
  active=active===index?-1:index;
  document.querySelectorAll('.flag-card').forEach(card=>{const open=card.dataset.flagId===flags[active]?.id;card.classList.toggle('is-open',open);card.setAttribute('aria-expanded',String(open));card.classList.remove('flag-card--near-bottom');});
  const openCard=document.querySelector('.flag-card.is-open');
  if(openCard&&openCard.getBoundingClientRect().bottom>innerHeight-220)openCard.classList.add('flag-card--near-bottom');
  syncHighlights();
  if(scroll&&active>=0)document.querySelector(`.diff-anchor[data-flag-id="${CSS.escape(flags[active].id)}"]`)?.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
 }
 function renderSummary(){
  if(!flags.length){summary.hidden=true;return;}summary.hidden=false;summary.replaceChildren();
  const count=document.createElement('span');count.className='flags-summary-count';const admins=flags.filter(flag=>flag.tier==='admin').length;
  count.innerHTML=`<strong>${flags.length} flag${flags.length===1?'':'s'}</strong>${admins?` · <em>${admins} for admin review</em>`:''}`;summary.append(count);
  const details=document.createElement('details');details.className='flags-filter';
  const trigger=document.createElement('summary');trigger.className='flags-filter__trigger';trigger.textContent='Filter types';details.append(trigger);
  const menu=document.createElement('div');menu.className='flags-filter__menu';menu.setAttribute('aria-label','Filter flags by type');
  const kinds=[...new Set(flags.map(flag=>flag.kind))];
  for(const kind of kinds){const label=document.createElement('label'),box=document.createElement('input');box.type='checkbox';box.checked=!filter.size||filter.has(kind);box.addEventListener('change',()=>{const next=filter.size?new Set(filter):new Set(kinds);if(box.checked)next.add(kind);else next.delete(kind);filter=next.size===kinds.length?new Set():next;renderCards();renderSummary();});label.append(box,document.createTextNode(labels[kind]||kind));menu.append(label);}
  details.append(menu);summary.append(details);
  const stepper=document.createElement('div');stepper.className='flags-stepper';
  for(const [word,delta] of [['Previous',-1],['Next',1]]){const button=document.createElement('button');button.type='button';button.textContent=word;button.addEventListener('click',()=>{const rows=visibleFlags();if(!rows.length)return;const position=rows.indexOf(flags[active]);activate(indexOf(rows[(position+delta+rows.length)%rows.length]),true);});stepper.append(button);}summary.append(stepper);
 }
 function renderCards(){
  if(!rail||!root)return;rail.replaceChildren();const table=$('#flags-diff table');if(table)window.PalimpsestFlagsAnchoring.unwrap(table);
  const visible=visibleFlags(),resolved=table?window.PalimpsestFlagsAnchoring.resolve(table,visible):{anchored:[],unanchored:visible};
  resolved.anchored.forEach(({flag,marks})=>{const index=indexOf(flag);marks.forEach(mark=>{mark.addEventListener('mouseenter',()=>setHover(index,true));mark.addEventListener('mouseleave',()=>setHover(index,false));mark.addEventListener('click',event=>{event.stopPropagation();activate(index,true);});});rail.append(card(flag,index));});
  tray.replaceChildren();tray.hidden=!resolved.unanchored.length;
  if(resolved.unanchored.length){const heading=document.createElement('h3');heading.textContent='Unanchored flags';const list=document.createElement('ol');list.className='flags-unanchored-list';resolved.unanchored.forEach(flag=>list.append(card(flag,indexOf(flag))));tray.append(heading,list);}
  active=-1;hovered=-1;syncHighlights();
 }
 function receive(data){
  flags=Array.isArray(data.flags)?data.flags:[];let diff=$('#flags-diff'),pane=$('.flags-diff-pane');
  if(data.diff_html&&!diff){diff=document.createElement('div');diff.id='flags-diff';pane.querySelector('.flags-unavailable')?.remove();pane.prepend(diff);}
  if(diff&&data.diff_html)diff.innerHTML=data.diff_html;renderSummary();renderCards();
 }
 function current(){const select=$('#flags-revision');return {topic:root.dataset.topic,lang:select.selectedOptions[0]?.dataset.lang||root.dataset.lang,revision:Number(select.value)};}
 function renderSeverity(){const option=$('#flags-revision')?.selectedOptions[0],chips=$('.flags-severity-chips');if(!option||!chips)return;const admin=Number(option.dataset.admin||0),review=Number(option.dataset.review||0);chips.replaceChildren();if(admin){const chip=document.createElement('span');chip.className='flags-severity-chip flags-severity-chip--admin';chip.textContent=admin+' admin';chips.append(chip);}if(review){const chip=document.createElement('span');chip.className='flags-severity-chip';chip.textContent=review+' review';chips.append(chip);}}
 async function audit(scan){const status=$('#scan-status');status.textContent='Checking revision…';try{const response=await fetch('/api/flags/audit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...current(),scan})}),data=await response.json();if(!response.ok||data.status==='error')throw Error(data.error||'Audit unavailable');receive(data);status.textContent=data.status==='ok'?'Audit loaded':data.error||'Not scanned';}catch(error){status.textContent=error.message;}}
 async function scanAll(){const select=$('#flags-revision'),status=$('#scan-status'),original=select.value;for(let index=0;index<select.options.length;index++){select.selectedIndex=index;status.textContent=`Scanning ${index+1} of ${select.options.length}…`;await audit(true);}select.value=original;await audit(false);}
 $('#flags-revision')?.addEventListener('change',()=>{renderSeverity();audit(false);});$('#scan-revisions')?.addEventListener('click',scanAll);renderSeverity();
 try{const data=JSON.parse($('#flags-data')?.textContent||'null');if(data)receive(data);}catch(error){}if(new URLSearchParams(location.search).get('scan')==='1')scanAll();
})();
