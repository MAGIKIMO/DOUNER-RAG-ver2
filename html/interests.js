'use strict';
(()=>{
  const $=id=>document.getElementById(id),KEY='donga.notice.interests.v1';let active=false,epoch=0;
  const el=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
  try{const p=JSON.parse(localStorage.getItem(KEY)||localStorage.getItem('donga.student.v1')||'{}');$('interest-department').value=p.department||'';$('interest-year').value=p.admission_year||p.year||'';for(const input of document.querySelectorAll('[name="interest"]'))input.checked=(p.interests||[]).includes(input.value);}catch{}
  function preferences(){return {department:$('interest-department').value.trim(),admission_year:$('interest-year').value?Number($('interest-year').value):null,interests:[...document.querySelectorAll('[name="interest"]:checked')].map(x=>x.value)};}
  async function post(path,body){const r=await fetch('/api/v1/notices/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{}),cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'관심 공지를 불러오지 못했습니다.');return d;}
  async function load(){
    if(!active)return;const version=++epoch;$('interest-status').textContent='관심 공지 확인 중…';$('interest-results').replaceChildren();
    try{const data=await post('recommend',preferences());if(version!==epoch||!active)return;
      $('interest-status').textContent=data.message+(data.candidate_limit_reached?' 검색 후보가 많아 최신 1,000건에서 골랐습니다.':'');
      if(!data.items.length)$('interest-results').append(el('p','현재 조건에 맞는 수집 공지가 없습니다. 다른 관심 분야를 선택해 보세요.'));
      for(const item of data.items){
        const card=el('article','');card.className='interest-card';card.append(el('h4',item.title),el('p',item.category+' · 게시 '+item.published_at.slice(0,10)),el('p',item.reasons.join(' / ')));
        card.append(el('p',item.deadline.date?'신청 관련 날짜: '+item.deadline.date+' · 정확한 마감 시각·적용 조건 확인 필요':'신청 기한을 자동 확인하지 못했습니다.'));
        if(item.deadline.evidence)card.append(el('blockquote',item.deadline.evidence));
        card.append(el('p','본문 발췌'),el('pre',item.excerpt));
        if(item.checked_at)card.append(el('p','수집 확인: '+new Date(item.checked_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})+' (한국 시간)'));
        const link=el('a','공식 원문');try{const url=new URL(item.url);if(url.protocol==='https:'&&url.hostname.endsWith('.donga.ac.kr')){link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}}catch{}
        const button=el('button','내용·신청 조건 설명하기');button.type='button';const answer=el('div','');answer.className='notice-answer';answer.setAttribute('aria-live','polite');
        button.addEventListener('click',async()=>{button.disabled=true;answer.textContent='본문과 추출된 첨부자료를 읽는 중…';try{const result=await post(item.id+'/summary');if(version===epoch&&active){answer.textContent=result.answer;const list=el('ul','');for(const source of result.sources||[]){const u=new URL(source.url);if(u.protocol!=='https:'||!u.hostname.endsWith('.donga.ac.kr'))continue;const li=el('li',''),a=el('a','['+source.id+'] '+source.title);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';li.append(a);list.append(li);}answer.append(list);}}catch(e){if(version===epoch&&active)answer.textContent=e.message;}finally{button.disabled=false;}});
        card.append(button,answer);$('interest-results').append(card);
      }
    }catch(e){if(version===epoch)$('interest-status').textContent=e.message;}
  }
  $('interest-form').addEventListener('submit',event=>{event.preventDefault();try{localStorage.setItem(KEY,JSON.stringify(preferences()));}catch{}load();});
  window.addEventListener('personal-demo-session',event=>{active=event.detail;epoch++;$('interest-results').replaceChildren();$('interest-status').textContent='';if(active)load();});
  $('brief-refresh').addEventListener('click',load);
})();
