'use strict';
(()=>{
 function priorities(tasks,events=[],deadlines=[],now=Date.now()){
  const result=[];
  for(const t of tasks.filter(t=>!t.done)){
   const at=t.due?Date.parse(t.due+'+09:00'):NaN;
   result.push({id:'notice:'+t.id,title:t.title,at,kind:'저장한 할 일',reason:!Number.isFinite(at)?'마감일 미설정':at<now?'마감 시간 지남 — 처리 여부 확인':at-now<86400000?'24시간 이내 마감':'다가오는 마감'});
  }
  for(const e of events)if(e.at>=now)result.push({id:'schedule:'+e.id,title:e.name,at:e.at,kind:'등록 일정',reason:'직접 등록한 수업·시험 일정'});
  for(const d of deadlines){const at=Date.parse(d.due_at);if(Number.isFinite(at))result.push({id:'lms:'+d.id+':'+d.course,title:d.course+' · '+d.title,at,kind:'LMS 과제',reason:d.submission_state==='unknown'?'제출 상태 미확인':'제출 완료로 표시되지 않음'});}
  return result.sort((a,b)=>(Number.isFinite(a.at)?a.at:Infinity)-(Number.isFinite(b.at)?b.at:Infinity));
 }
 const api={priorities};globalThis.DounerTasks=api;if(typeof module!=='undefined')module.exports=api;
})();
