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
 return {DAY,kinds,floor,next,periods,bins};
});
