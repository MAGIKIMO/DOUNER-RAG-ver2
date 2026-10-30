const {test}=require('node:test'),assert=require('node:assert/strict'),{priorities}=require('../html/task-core.js');
test('completed tasks excluded; KST deadlines sorted with unknown dates last',()=>{
 const now=Date.parse('2026-10-01T00:00:00Z');
 const result=priorities([{id:1,title:'unknown',due:'',done:false},{id:2,title:'soon',due:'2026-10-01T10:00',done:false},{id:3,title:'done',due:'2026-09-01T10:00',done:true}],[],[],now);
 assert.deepEqual(result.map(x=>x.title),['soon','unknown']);assert.equal(result[0].at,now+3600000);
});
test('LMS and manually registered schedules join without changing source data',()=>{
 const now=Date.now(),events=[{id:1,name:'class',at:now+60000}];
 const result=priorities([],events,[{id:2,course:'CS',title:'assignment',due_at:new Date(now+120000).toISOString(),submission_state:'unknown'}],now);
 assert.equal(result.length,2);assert.equal(result[0].kind,'등록 일정');assert.equal(result[1].reason,'제출 상태 미확인');assert.equal(events.length,1);
});
