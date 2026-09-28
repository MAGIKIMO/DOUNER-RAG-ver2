'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const status=$('account-status');let epoch=0;
  const demo=document.body.dataset.personalDemo==='true';
  const prefix=demo?'/api/v1/personal-canvas/':'/api/v1/canvas/';
  async function api(path, body){
    const response=await fetch(prefix+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',
      headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.');
    return data;
  }
  function clearPrivate(){epoch++;$('private-panel').hidden=true;$('private-answer').textContent='';$('private-sources').replaceChildren();$('canvas-course').replaceChildren();$('private-question').value='';$('private-consent').checked=false;if(demo)window.dispatchEvent(new CustomEvent('personal-demo-session',{detail:false}));}
  async function load(){
    clearPrivate();const version=epoch;
    try{
      const data=await api('status');if(version!==epoch)return;
      $('login-panel').hidden=data.authenticated;$('canvas-login').disabled=!data.configured;
      status.textContent=!data.configured?'학교 앱 승인과 HTTPS 설정을 준비 중입니다. 공용 학교 정보 질문은 계속 이용할 수 있어요.':data.authenticated?'Canvas에 연결되어 있습니다.':'Canvas로 로그인해 주세요.';
      if(demo)status.textContent=!data.configured?'본인 데모 설정을 확인해 주세요.':data.authenticated?'개발자 본인 계정으로 연결된 데모입니다.':'발표용 비밀번호로 데모에 로그인해 주세요.';
      if(!data.authenticated)return;
      $('private-panel').hidden=false;
      const result=await api('courses');if(version!==epoch)return;
      for(const c of result.courses){const option=document.createElement('option');option.value=c.id;option.textContent=c.name+(c.term?' · '+c.term:'');$('canvas-course').append(option);}
      $('course-status').textContent=!result.complete?'목록 일부만 조회되었습니다.':result.courses.length?'조회된 과목을 선택해 주세요.':'조회 가능한 활성 수강 과목이 없습니다.';
      if(demo)window.dispatchEvent(new CustomEvent('personal-demo-session',{detail:true}));
    }catch(error){if(version===epoch)status.textContent=error.message;}
  }
  $('canvas-login').addEventListener('click',async()=>{
    $('canvas-login').disabled=true;
    try{
      if(demo){const key=$('demo-key').value;$('demo-key').value='';await api('login',{admin_key:key});await load();}
      else{const data=await api('start',{});location.assign(data.authorize_url);}
    }
    catch(error){status.textContent=error.message;$('canvas-login').disabled=false;}
  });
  $('canvas-logout').addEventListener('click',async()=>{
    clearPrivate();try{await api('logout',{});await load();}catch(error){status.textContent=error.message;}
  });
  $('canvas-disconnect')?.addEventListener('click',async()=>{
    if(!confirm('LMS 연결과 이 서비스의 Canvas 계정을 삭제할까요?'))return;
    clearPrivate();try{const data=await api('disconnect',{});await load();status.textContent=data.remote_revoked?'연결과 계정을 삭제했습니다.':'서비스의 연결 정보는 삭제했습니다. Canvas 설정의 승인된 통합에서도 접근 권한을 해제해 주세요.';}
    catch(error){status.textContent=error.message;}
  });
  $('private-form').addEventListener('submit',async event=>{
    event.preventDefault();const version=epoch;$('private-send').disabled=true;$('private-answer').textContent='과목 자료를 조회하고 답변하는 중…';$('private-sources').replaceChildren();
    try{
      const data=await api('ask',{course_id:$('canvas-course').value,question:$('private-question').value.trim(),consent_to_llm:$('private-consent').checked});
      if(version!==epoch)return;
      $('private-answer').textContent=data.answer;
      for(const source of data.sources||[]){const url=new URL(source.url);if(url.protocol!=='https:'||!url.hostname.endsWith('.donga.ac.kr'))continue;const li=document.createElement('li'),a=document.createElement('a');a.textContent=source.title;a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';li.append(a);$('private-sources').append(li);}
    }catch(error){if(version===epoch)$('private-answer').textContent=error.message;}
    finally{$('private-send').disabled=false;}
  });
  window.addEventListener('pagehide',clearPrivate);
  window.addEventListener('pageshow',event=>{if(event.persisted)load();});
  const outcome=new URLSearchParams(location.search).get('oauth');
  if(outcome)history.replaceState(null,'','account.html');
  load().then(()=>{if(outcome==='failed')status.textContent='Canvas 연결이 취소되었거나 만료되었습니다. 다시 로그인해 주세요.';});
})();
