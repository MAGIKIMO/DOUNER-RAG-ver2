"use strict";
(() => {
  const PROFILE='donga.student.v1', SAVED='donga.bookmarks.v1', CLIENT='donga.feedback-client.v1';
  const read=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}};
  const write=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value));return true;}catch{return false;}};
  const el=(tag,text,className)=>{const n=document.createElement(tag);n.textContent=text;if(className)n.className=className;return n;};
  const safeURL=value=>{try{const u=new URL(value);return u.protocol==='https:'||u.protocol==='http:'?u.href:null;}catch{return null;}};
  let profile=read(PROFILE,{});if(!profile||typeof profile!=='object'||Array.isArray(profile))profile={};
  let saved=read(SAVED,[]);if(!Array.isArray(saved))saved=[];
  saved=saved.filter(s=>s&&typeof s.title==='string'&&safeURL(s.url)).slice(0,50);
  let currentReport=null;
  const status=document.querySelector('#student-status');
  const message=text=>{status.textContent=text;};
  function context(base){
    const value={};
    if(typeof profile.department==='string'&&profile.department)value.department=profile.department.slice(0,100);
    if(Number.isInteger(profile.year)&&profile.year>=1970&&profile.year<=new Date().getFullYear())value.admission_year=profile.year;
    if(['1','2'].includes(profile.campus))value.meal_campus=profile.campus;
    const result={...value,...(base||{})};
    const selected=document.querySelector('#category')?.value;
    if(selected&&/학과|학부/.test(selected))result.department=selected;
    return result;
  }
  function fillProfile(){
    document.querySelector('#profile-department').value=profile.department||'';
    document.querySelector('#profile-year').value=profile.year||'';
    document.querySelector('#profile-campus').value=profile.campus||'';
  }
  function renderSaved(){
    const container=document.querySelector('#saved-notices');container.replaceChildren();
    const now=Date.now();let soon=0;
    const sorted=[...saved].sort((a,b)=>(Date.parse(a.deadline)||Infinity)-(Date.parse(b.deadline)||Infinity));
    for(const item of sorted){
      const row=el('article','','saved-notice');const link=el('a',item.title);link.href=safeURL(item.url);link.target='_blank';link.rel='noopener noreferrer';row.append(link);
      const due=Date.parse(item.deadline);let label='마감일 미설정';
      if(Number.isFinite(due)){
        const when=new Date(due).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'});
        if(due<now)label=`마감 지남 · ${when}`;
        else if(due-now<=3*86400000){soon++;label=`마감 임박 · ${when}`;}
        else label=`마감 · ${when}`;
        label+=' (한국 시간, 직접 지정)';
      }
      row.append(el('p',label,'micro'));
      const edit=el('button','마감일 설정');edit.type='button';edit.addEventListener('click',()=>editDeadline(item));
      const remove=el('button','저장 취소');remove.type='button';remove.addEventListener('click',()=>{
        const next=saved.filter(s=>s.url!==item.url);
        if(!write(SAVED,next)){message('브라우저에 저장할 수 없습니다.');return;}
        saved=next;renderSaved();message('관심 공지에서 제외했습니다.');syncButtons();
      });
      row.append(edit,remove);container.append(row);
    }
    if(!saved.length)container.append(el('p','답변 아래 공지에서 저장을 눌러 보세요.','micro'));
    document.querySelector('#saved-count').textContent=String(saved.length);
    document.querySelector('#due-count').textContent=soon?`· 마감 임박 ${soon}건`:'';
    document.querySelector('#deadline-summary').textContent=soon?`3일 안에 마감하는 관심 공지가 ${soon}건 있습니다.`:'3일 안에 마감하는 관심 공지가 없습니다.';
  }
  function editDeadline(item){
    const dialog=document.querySelector('#deadline-dialog');
    dialog.dataset.url=item.url;document.querySelector('#deadline-title').textContent=item.title;
    const input=document.querySelector('#deadline-input');
    input.value=Number.isFinite(Date.parse(item.deadline))?new Date(Date.parse(item.deadline)+9*3600000).toISOString().slice(0,16):'';
    dialog.showModal();
  }
  function syncButtons(){
    document.querySelectorAll('[data-save-url]').forEach(button=>{
      const exists=saved.some(s=>s.url===button.dataset.saveUrl);
      button.textContent=exists?'저장됨':'공지 저장';button.setAttribute('aria-pressed',String(exists));
    });
  }
  function sourceButton(source){
    const url=safeURL(source.url);if(!url)return null;
    const button=el('button',saved.some(s=>s.url===url)?'저장됨':'공지 저장','save-notice');button.type='button';button.dataset.saveUrl=url;
    button.setAttribute('aria-pressed',String(saved.some(s=>s.url===url)));
    button.addEventListener('click',()=>{
      const existing=saved.find(s=>s.url===url);if(existing){editDeadline(existing);return;}
      if(saved.length>=50){message('관심 공지는 최대 50개까지 저장할 수 있습니다.');return;}
      const next=[...saved,{title:String(source.title).slice(0,1000),url,deadline:null}];
      if(!write(SAVED,next)){message('브라우저에 저장할 수 없습니다.');return;}
      saved=next;renderSaved();syncButtons();message('관심 공지에 저장했습니다. 마감일은 직접 설정할 수 있습니다.');
    });return button;
  }
  function reportButton(question,data){
    const button=el('button','답변 오류 신고','report-answer');button.type='button';
    button.addEventListener('click',()=>{
      currentReport={question:question.slice(0,2000),answer:data.answer.slice(0,8000),sources:(data.sources||[]).slice(0,20).map(s=>({title:String(s.title).slice(0,1000),url:String(s.url).slice(0,2000)}))};
      document.querySelector('#report-preview').textContent=`질문: ${currentReport.question}\n\n답변: ${currentReport.answer}\n\n참고자료:\n${currentReport.sources.map(s=>s.title+'\n'+s.url).join('\n')}`;
      document.querySelector('#report-comment').value='';document.querySelector('#report-status').textContent='';document.querySelector('#report-dialog').showModal();
    });return button;
  }
  document.querySelector('#profile-form').addEventListener('submit',event=>{
    event.preventDefault();const yearValue=document.querySelector('#profile-year').value;
    const next={department:document.querySelector('#profile-department').value.trim(),year:yearValue?Number(yearValue):null,campus:document.querySelector('#profile-campus').value};
    if(next.year&&(next.year<1970||next.year>new Date().getFullYear())){message('입학연도를 확인해 주세요.');return;}
    if(!write(PROFILE,next)){message('브라우저에 설정을 저장할 수 없습니다.');return;}
    profile=next;window.dispatchEvent(new Event('student-profile-changed'));message('기본 정보를 이 브라우저에 저장했습니다.');
  });
  document.querySelector('#profile-delete').addEventListener('click',()=>{
    if(!write(PROFILE,{})){message('설정을 지우지 못했습니다.');return;}
    profile={};fillProfile();window.dispatchEvent(new Event('student-profile-changed'));message('저장한 기본 정보를 지웠습니다.');
  });
  document.querySelector('#deadline-form').addEventListener('submit',event=>{
    event.preventDefault();const dialog=document.querySelector('#deadline-dialog');const raw=document.querySelector('#deadline-input').value;
    const due=raw?new Date(raw+':00+09:00'):null;
    if(due&&!Number.isFinite(due.getTime()))return;
    const next=saved.map(s=>s.url===dialog.dataset.url?{...s,deadline:due?due.toISOString():null}:s);
    if(!write(SAVED,next)){message('마감일을 저장하지 못했습니다.');return;}
    saved=next;dialog.close();renderSaved();message('마감일 설정을 저장했습니다.');
  });
  document.querySelectorAll('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  document.querySelector('#report-form').addEventListener('submit',async event=>{
    event.preventDefault();if(!currentReport)return;
    const button=document.querySelector('#report-send');button.disabled=true;const reportStatus=document.querySelector('#report-status');
    let client=read(CLIENT,null);if(typeof client!=='string'){client=crypto.randomUUID();write(CLIENT,client);}
    try{
      const response=await fetch('/api/v1/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...currentReport,client_id:client,reason:document.querySelector('#report-reason').value,comment:document.querySelector('#report-comment').value}),signal:AbortSignal.timeout(15000)});
      if(!response.ok)throw new Error(response.status===429?'신고 요청이 많습니다. 잠시 후 다시 시도해 주세요.':'전송에 실패했습니다. 다시 시도해 주세요.');
      const result=await response.json();currentReport=null;document.querySelector('#report-dialog').close();message(`오류 신고를 접수했습니다. 접수번호 ${result.id}`);
    }catch(error){reportStatus.textContent=error.name==='TimeoutError'?'응답 시간이 초과되었습니다.':error.message;}finally{button.disabled=false;}
  });
  window.StudentUI={context,sourceButton,reportButton};
  fillProfile();renderSaved();setInterval(renderSaved,60000);
})();
