const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const ctx=vm.createContext({});vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../html/planner.js'),'utf8'),ctx);const p=ctx.DongaPlanner;
test('Korean date crosses UTC midnight correctly',()=>{assert.equal(p.koreaDate(Date.parse('2026-09-22T16:00:00Z')),'2026-09-23');});
test('weekly classes respect semester bounds and Korean weekday',()=>{
 const now=Date.parse('2026-09-23T08:00:00+09:00');const entries=[{id:'x',name:'Class',kind:'weekly',weekday:'3',time:'09:00',start:'2026-09-01',end:'2026-09-25'}];const list=p.expand(entries,now);assert.equal(list.length,1);assert.equal(list[0].date,'2026-09-23');assert.equal(list[0].at-now,3600000);
});
test('exam reminder excludes past and distant events',()=>{const now=Date.parse('2026-09-23T08:00:00+09:00');const list=p.expand([{id:'x',name:'Exam',kind:'exam',date:'2026-09-23',time:'08:30'},{id:'y',name:'Old',kind:'exam',date:'2026-09-22',time:'08:30'}],now);assert.equal(list.length,1);assert.equal(p.reminders(list,[],now).length,1);assert.equal(p.reminders(list,[],now+3600000).length,0);});
test('deadline reminders stop at expiry',()=>{const now=Date.parse('2026-09-23T08:00:00+09:00');const d={url:'source',course:'Course',title:'Assignment',due_at:'2026-09-24T08:00:00+09:00'};assert.equal(p.reminders([], [d],now).length,1);assert.equal(p.reminders([], [d],now-1).length,0);});
