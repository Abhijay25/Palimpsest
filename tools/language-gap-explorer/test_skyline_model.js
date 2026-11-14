const assert=require('node:assert/strict');
const M=require('./static/skyline-model.js');
const point=(stamp,n,state='complete')=>({stamp,state,counts:{coverage:n,framing:0,contradiction:0}});
let result=M.bins([point('2025-01-02T00:00:00Z',7),point('2025-01-20T00:00:00Z',4)],Date.UTC(2020,0,1),Date.UTC(2026,0,1),12);
assert.equal(result.unit,'year');assert.equal(result.bins.at(-1).total,4,'Use the latest observation, not 7+4');
assert.equal(result.bins[0].total,null,'Unknown year is not zero');
result=M.bins([point('2025-01-01T00:00:00Z',0)],Date.UTC(2025,0,1),Date.UTC(2025,0,2),7);
assert.equal(result.unit,'day');assert.equal(result.bins[0].total,0);assert.ok(result.bins[0].observation);
result=M.bins([point('2025-01-01T00:00:00Z',5),point('2025-01-02T00:00:00Z',8,'unknown')],Date.UTC(2025,0,1),Date.UTC(2025,0,3),7);
assert.equal(result.bins[1].total,null,'Never carry a previous count into an unobserved day');
result=M.bins([],Date.UTC(2025,0,1),Date.UTC(2025,6,30),7);assert.ok(result.bins.length<=7);
console.log('Skyline calendar aggregation checks passed.');
const phases=[{stamp:'2025-01-01T00:00:00Z',state:'complete',counts:{coverage:1,framing:1,contradiction:0}},{stamp:'2025-01-02T00:00:00Z',state:'complete',counts:{coverage:1,framing:1,contradiction:0}}];
const cols=M.bins(phases,Date.UTC(2025,0,1),Date.UTC(2025,0,3),12).bins;
const makeCell=(stamp,kind,pair='EN–FI')=>({stamp,kind,pair_kinds:[{pair,kind}]});
const rows=[{id:'a',title:'Peace',cells:[makeCell(phases[0].stamp,'coverage'),makeCell(phases[1].stamp,'framing')]},{id:'b',title:'Army',cells:[makeCell(phases[0].stamp,'contradiction','FI–SV')]}];
assert.deepEqual(M.visibleRows(rows,cols).map(r=>r.id),['b','a'],'Strongest observed category ranks first');
assert.deepEqual(M.visibleRows(rows,cols,{pair:'EN–FI'}).map(r=>r.id),['a'],'Pair scope excludes another pair');
assert.deepEqual(M.visibleRows(rows,cols,{changed:true}).map(r=>r.id),['a'],'Missing findings are not category changes');
assert.equal(M.visibleRows(rows,cols,{matches:[]}).length,0);
for(const unit of ['year','month','week','day'])for(const n of [7,12]){
 const [from,to]=M.windowForUnit(Date.UTC(2025,6,29),unit,n,Date.UTC(2020,0,1),Date.UTC(2025,6,30));
 assert.ok(from>=Date.UTC(2020,0,1)&&to<=Date.UTC(2025,6,30)&&to>from);
 const view=M.bins([],from,to,n);assert.equal(view.unit,unit);assert.ok(view.bins.length<=n);
}
console.log('Heatmap scope, ranking and calendar zoom checks passed.');
