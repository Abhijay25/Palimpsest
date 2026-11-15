/* Sparse detector source-time metadata. This module never fetches or scans. */
(function(root,factory){const value=factory();if(typeof module==='object'&&module.exports)module.exports=value;else root.IssueHistogram=value;})(typeof window==='undefined'?globalThis:window,()=>{
 'use strict';
 const labels={coverage:'Additional context',framing:'Different framing',contradiction:'Possible contradiction',FACT:'Fact',FRAMING:'Wording',MOTIVE:'Motive',REMOVED_CONTEXT:'Removed context',HIDDEN_TEXT:'Hidden text',CITATION_DATE:'Citation date',CITED_PAGE:'Cited page',CHERRY_PICK:'Selective quote',OUT_OF_SYNC:'Out of sync'};
 const kinds=Object.keys(labels);
 function bounds(original,detector){const stamps=[...original,...(detector?.assessments||[]).map(a=>a.source_stamp),...(detector?.coverage||[]).map(a=>a.source_stamp)].filter(s=>s&&Number.isFinite(Date.parse(s))).sort((a,b)=>Date.parse(a)-Date.parse(b));return stamps.length?[stamps[0],stamps.at(-1)]:original;}
 function coverage(detector,start,end){const within=row=>{const t=Date.parse(row.source_stamp);return t>=start&&t<end;},attempts=(detector?.coverage||[]).filter(within),success=(detector?.assessments||[]).filter(within);return {assessed:success.length,empty:success.filter(s=>s.empty&&s.state==='completed').length,partial:success.filter(s=>s.state==='partial').length,failed:attempts.filter(s=>s.state==='failed').length,running:attempts.filter(s=>s.state==='running').length,state:!success.length?(attempts.some(s=>s.state==='failed')?'failed':attempts.some(s=>s.state==='running')?'running':'not assessed'):success.some(s=>s.state==='partial')?'partial':'completed'};}
 return {kinds,labels,bounds,coverage};
});
