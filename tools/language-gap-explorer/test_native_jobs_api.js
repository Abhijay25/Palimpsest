'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../infra/wiki/extensions/PalimpsestIssues/resources/issues.js'),'utf8');
const start=source.indexOf(' async function call('),end=source.indexOf(' function back(',start);
assert.ok(start>=0&&end>start,'The actual native request helper must be present.');
const requests=[];
const response=params=>({palimpsestissues:{status:'ok',op:params.op}});
const context={query:{revision:'123'},config:{title:'Winter War'},api:{
 get:async params=>{requests.push({method:'GET',params});return response(params);},
 postWithToken:async(token,params)=>{requests.push({method:'POST',token,params});return response(params);}
}};
vm.createContext(context);vm.runInContext(source.slice(start,end)+';this.nativeCall=call;',context);
(async()=>{
 for(const op of ['list','detail','versions','cached','health','jobpolicy','jobs','job']){
  const data=await context.nativeCall(op,{job:'exact-job'});assert.equal(data.op,op);
  const request=requests.at(-1);assert.equal(request.method,'GET');assert.equal(request.params.title,'Winter War');
 }
 for(const op of ['scan','review','translate','jobplan','enqueue']){
  await context.nativeCall(op,{revision:'123',plan:'exact-plan'},{mode:'page'});
  const request=requests.at(-1);assert.equal(request.method,'POST',op+' must never use GET');assert.equal(request.token,'csrf');
  assert.equal(request.params.mode,'page');assert.deepEqual(JSON.parse(request.params.selection),{revision:'123',plan:'exact-plan'});
 }
 const before=requests.length;
 context.api.postWithToken=async()=>{requests.push({method:'POST',failed:true});throw Error('fixture connection failure');};
 await assert.rejects(context.nativeCall('enqueue',{plan:'same-plan'}),/wiki request failed/);
 assert.equal(requests.length,before+1,'Transport failure must not silently retry an enqueue.');
 console.log('Native reads stay GET; planning, enqueue, scans, reviews and translation use POST/CSRF; failures do not auto-retry.');
})().catch(error=>{console.error(error);process.exitCode=1;});
