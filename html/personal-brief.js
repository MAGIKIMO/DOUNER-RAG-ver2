'use strict';
(()=>{
  const $=id=>document.getElementById(id),P=globalThis.DongaPlanner,KEY='donga.personal-demo.schedule.v1';
  const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
  let active=false,epoch=0,brief=null,events=[],busy=false,notify=false,entries=[];const notified=new Set();
  try{const saved=JSON.parse(localStorage.getItem(KEY)||'[]');if(Array.isArray(saved))entries=saved.slice(0,100);}catch{/* No stored schedule. */}
  async function get(url){const r=await fetch(url,{credentials:'same-origin',cache:'no-store'});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'자료를 불러오지 못했습니다.');return data;}
  function schedule(){
    if(!active)return;
    const now=Date.now();events=P.expand(entries,now);$('brief-events').replaceChildren();
    const next=events.find(e=>e.at>=now),today=P.koreaDate(now);
    $('today-glance').textContent=next?`다음 등록 일정: ${next.date===today?'오늘':next.date} ${next.time} · ${next.name}${next.place?' · '+next.place:''} (한국 시간)`:'다가오는 등록 일정이 없습니다. 시간표·시험 일정을 추가해 주세요.';
    for(const e of events){const li=node('li',`${e.date===P.koreaDate(now)?'오늘':e.date} ${e.time} · ${e.name}${e.place?' · '+e.place:''}${e.at<now?' (시작 시간 지남)':''} `),button=node('button','삭제');button.type='button';button.addEventListener('click',()=>{entries=entries.filter(x=>x.id!==e.id);save();schedule();});li.append(button);$('brief-events').append(li);}
    if(!events.length)$('brief-events').append(node('li','등록된 7일 이내 일정이 없습니다. 수업·시험 일정을 직접 추가해 주세요.'));
    reminders();
  }
  function save(){try{localStorage.setItem(KEY,JSON.stringify(entries));$('schedule-status').textContent='이 브라우저에 저장했습니다.';}catch{$('schedule-status').textContent='브라우저 저장에 실패했습니다. 현재 화면에서만 유지됩니다.';}}
  function reminders(){
    if(!active)return;
    const items=P.reminders(events,brief?.deadlines||[],Date.now());$('brief-reminders').replaceChildren();
    for(const item of items){$('brief-reminders').append(node('p','알림 · '+item.text));if(notify&&!notified.has(item.id)){try{new Notification('douner',{body:item.text});notified.add(item.id);}catch{$('notify-status').textContent='이 브라우저에서는 PC 알림을 지원하지 않습니다. 화면 알림을 확인해 주세요.';notify=false;}}}
  }
  async function meals(version){
    $('brief-meals').textContent='오늘 식단 확인 중…';
    try{
      const today=P.koreaDate(Date.now()),campus=$('brief-campus').value;
      const data=await get('/api/v1/meals?month='+today.slice(0,7)+'&campus='+campus);
      if(version!==epoch||campus!==$('brief-campus').value)return;
      const day=data.days.find(d=>d.date===today);$('brief-meals').replaceChildren();
      if(!day)throw Error('오늘 날짜의 식단을 확인하지 못했습니다.');
      if(day.checked_at)$('brief-meals').append(node('p','수집 확인: '+new Date(day.checked_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})+' (한국 시간)'));
      if(day.stale)$('brief-meals').append(node('p','오늘 갱신되지 않은 자료입니다. 최신 변경은 확인되지 않았습니다.'));
      if(!day.menus.length)$('brief-meals').append(node('p',day.status==='not_collected'?'오늘 식단은 아직 수집하지 못했습니다.':'공식 식단표에 메뉴가 미등록되어 있습니다. 휴무를 뜻하지는 않습니다.'));
      if(day.menus.length){
        const names=[...new Set(day.menus.map(m=>m.cafeteria))],key='douner.meal-cafeteria.'+campus;
        const label=node('label','식당'),select=node('select',''),content=node('div','');
        select.id='brief-cafeteria';label.htmlFor=select.id;content.className='selected-meal';content.setAttribute('aria-live','polite');
        for(const name of names){const option=node('option',name);option.value=name;select.append(option);}
        try{const saved=localStorage.getItem(key);if(names.includes(saved))select.value=saved;}catch{}
        function show(){content.replaceChildren();for(const m of day.menus.filter(m=>m.cafeteria===select.value)){content.append(node('h4',m.type),node('pre',m.text));}}
        select.addEventListener('change',()=>{try{localStorage.setItem(key,select.value);}catch{}show();});
        $('brief-meals').append(label,select,content);show();
      }
    }catch(e){if(version===epoch)$('brief-meals').textContent=e.message;}
  }
  async function refresh(){
    if(!active||busy)return;busy=true;const version=epoch;$('brief-refresh').disabled=true;$('brief-summary').textContent='본인 LMS에서 가까운 마감을 확인하고 있어요…';
    schedule();const mealJob=meals(version);
    try{
      const data=await get('/api/v1/personal-canvas/brief');if(version!==epoch)return;brief=data;$('brief-deadlines').replaceChildren();
      const today=P.koreaDate(Date.now()),todayEvents=events.filter(e=>e.date===today&&e.at>=Date.now());
      $('brief-summary').textContent=`오늘 남은 등록 일정 ${todayEvents.length}개, 7일 이내 마감 과제 ${data.deadlines.length}개가 조회됐어요. 아래에서 확인하세요.`;
      $('brief-coverage').textContent=`한국 시간 ${new Date(data.fetched_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})} 조회 · ${data.course_count}개 중 ${data.courses_checked}개 과목 확인. `+(data.complete?'조회된 과목 범위의 결과입니다.':'일부 과목을 조회하지 못했거나 조회 제한에 도달했습니다. ')+(data.undated_assignments?`마감일 없는 항목 ${data.undated_assignments}개는 일정에 표시하지 않았습니다.`:'');
      for(const d of data.deadlines){const li=node('li',`${new Date(d.due_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})} · ${d.course} · ${d.title} · ${d.submission_state==='unknown'?'제출 상태 미확인':'제출 완료로 표시되지 않음'} `),a=node('a','LMS 확인');a.href=d.url;a.target='_blank';a.rel='noopener noreferrer';li.append(a);$('brief-deadlines').append(li);}
      if(!data.deadlines.length)$('brief-deadlines').append(node('li','현재 조회 결과에 해당하는 마감이 없습니다. 조회 실패·기한 미등록·외부 도구 과제는 별도 확인이 필요합니다.'));
      reminders();
    }catch(e){if(version===epoch){brief=null;$('brief-summary').textContent=e.message;$('brief-deadlines').replaceChildren();$('brief-coverage').textContent='LMS 과제 조회 실패 — 과제가 없다는 의미가 아닙니다.';}}
    finally{await mealJob;if(version===epoch){busy=false;$('brief-refresh').disabled=false;}}
  }
  window.addEventListener('personal-demo-session',event=>{active=event.detail;epoch++;brief=null;busy=false;$('brief-panel').hidden=!active;for(const id of ['brief-summary','brief-events','brief-deadlines','brief-meals','brief-reminders','brief-coverage'])$(id).replaceChildren();if(active)refresh();else{notify=false;notified.clear();}});
  $('brief-refresh').addEventListener('click',refresh);$('brief-campus').addEventListener('change',()=>{if(active)meals(epoch);});
  $('brief-notify').addEventListener('click',async()=>{if(!('Notification' in window)){$('notify-status').textContent='이 브라우저는 PC 알림을 지원하지 않습니다.';return;}const version=epoch;const permission=await Notification.requestPermission();if(version!==epoch||!active)return;notify=permission==='granted';$('notify-status').textContent=notify?'화면이 열려 있는 동안 수업·시험 1시간 전, 과제 마감 24시간 이내에 알립니다. 앱 종료 시 알림은 중지됩니다.':'PC 알림을 허용하지 않았습니다. 화면 안에서만 알려드립니다.';reminders();});
  function kind(){const weekly=$('schedule-kind').value==='weekly';$('schedule-weekly').hidden=!weekly;$('schedule-once').hidden=weekly;$('schedule-date').required=!weekly;$('schedule-start').required=weekly;$('schedule-end').required=weekly;}
  $('schedule-kind').addEventListener('change',kind);kind();
  $('schedule-form').addEventListener('submit',event=>{event.preventDefault();if(entries.length>=100){$('schedule-status').textContent='최대 100개입니다. 기존 일정을 삭제해 주세요.';return;}const name=$('schedule-name').value.trim();if(!name)return;const item={id:crypto.randomUUID(),name,kind:$('schedule-kind').value,time:$('schedule-time').value,place:$('schedule-place').value.trim(),date:$('schedule-date').value,weekday:$('schedule-weekday').value,start:$('schedule-start').value,end:$('schedule-end').value};if(item.kind==='weekly'&&item.end<item.start){$('schedule-status').textContent='종료일은 시작일 이후여야 합니다.';return;}entries.push(item);save();schedule();});
  $('schedule-clear').addEventListener('click',()=>{if(confirm('이 브라우저에 등록한 일정을 모두 삭제할까요?')){entries=[];save();schedule();}});
  setInterval(()=>{if(active)schedule();},60000);
  setInterval(()=>{if(active&&document.visibilityState==='visible')refresh();},600000);
  document.addEventListener('visibilitychange',()=>{if(active&&document.visibilityState==='visible'){schedule();refresh();}});
})();
