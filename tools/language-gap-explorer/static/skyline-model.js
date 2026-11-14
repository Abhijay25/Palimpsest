/* Calendar aggregation only. Missing observations are never carried forward. */
(function(root,factory){const model=factory();if(typeof module==='object'&&module.exports)module.exports=model;else root.SkylineModel=model;})(typeof window==='undefined'?globalThis:window,()=>{
 'use strict';
 const DAY=86400000,kinds=['coverage','framing','contradiction'];
 function floor(value,unit){const d=new Date(value);if(unit==='year')return Date.UTC(d.getUTCFullYear(),0,1);if(unit==='month')return Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),1);const day=Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate());return unit==='week'?day-((d.getUTCDay()+6)%7)*DAY:day;}
 function next(value,unit){const d=new Date(value);if(unit==='year')return Date.UTC(d.getUTCFullYear()+1,0,1);if(unit==='month')return Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1);return value+(unit==='week'?7:1)*DAY;}
 function periods(from,to,unit){const out=[];for(let start=floor(from,unit);start<to;start=next(start,unit)){out.push({start,end:next(start,unit)});if(out.length>400)break;}return out;}
 function bins(observations,from,to,maxColumns=12,kind='all'){
  const unit=['day','week','month','year'].find(unit=>periods(from,to,unit).length<=maxColumns)||'year';
  const result=periods(from,to,unit).map(period=>{
   const available=observations.filter(o=>{const t=Date.parse(o.stamp);return t>=Math.max(period.start,from)&&t<Math.min(period.end,to)&&o.state!=='unknown';}).sort((a,b)=>a.stamp.localeCompare(b.stamp));
   const complete=available.filter(o=>o.state==='complete');const observation=complete.at(-1)||available.at(-1)||null;
   const counts=observation?observation.counts:null;const total=counts?kinds.reduce((sum,k)=>sum+(kind==='all'||kind===k?counts[k]||0:0),0):null;
   return {...period,observation,counts,total};
  });return {unit,bins:result};
 }
 function shift(value,unit,count){const d=new Date(value);if(unit==='year')return Date.UTC(d.getUTCFullYear()+count,0,1);if(unit==='month')return Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+count,1);return value+count*(unit==='week'?7:1)*DAY;}
 function windowForUnit(anchor,unit,count,min,max){
  const last=next(floor(max-1,unit),unit);let start=shift(floor(anchor,unit),unit,-Math.floor((count-1)/2)),end=shift(start,unit,count);
  if(end>last){end=last;start=shift(end,unit,-count);}if(start<floor(min,unit)){start=floor(min,unit);end=shift(start,unit,count);}
  return [Math.max(min,start),Math.min(max,end)];
 }
 function visibleRows(rows,columns,{kind='all',pair='all',changed=false,matches=null,sort='controversial'}={}){
  const stamps=columns.map(c=>c.observation?.stamp),relevance=matches&&new Map(matches.map(m=>[m.id,m.relevance]));
  const result=[];
  for(const row of rows){if(relevance&&!relevance.has(row.id))continue;const byStamp=new Map(row.cells.map(c=>[c.stamp,c]));
   const cells=stamps.map(stamp=>{const c=byStamp.get(stamp);if(!c)return null;const pairs=pair==='all'?c.pair_kinds.filter(p=>kind==='all'||p.kind===kind):c.pair_kinds.filter(p=>p.pair===pair&&(kind==='all'||p.kind===kind));if(!pairs.length)return null;const strongest=pairs.reduce((a,b)=>kinds.indexOf(a.kind)>kinds.indexOf(b.kind)?a:b);return {...c,kind:strongest.kind,supporting_pairs:pairs.filter(p=>p.kind===strongest.kind).map(p=>p.pair)};});
   const observed=cells.filter(Boolean);if(!observed.length)continue;
   const distinct=new Set(observed.map(c=>c.kind));if(changed&&distinct.size<2)continue;
   const strongest=Math.max(...observed.map(c=>kinds.indexOf(c.kind))),last=Math.max(...observed.map(c=>Date.parse(c.stamp)));
   result.push({...row,visibleCells:cells,strongest,last,relevance:relevance?.get(row.id)||0});
  }
  result.sort((a,b)=>sort==='alphabetical'?a.title.localeCompare(b.title)||a.id.localeCompare(b.id):sort==='recent'?b.last-a.last||a.id.localeCompare(b.id):sort==='relevance'?b.relevance-a.relevance||a.id.localeCompare(b.id):b.strongest-a.strongest||a.id.localeCompare(b.id));
  return result;
 }
 return {DAY,kinds,floor,next,periods,bins,windowForUnit,visibleRows};
});
