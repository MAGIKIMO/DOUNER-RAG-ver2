'use strict';
(()=>{
 const $=id=>document.getElementById(id),campus=$('home-campus'),cafeteria=$('home-cafeteria'),status=$('home-meal-status'),menu=$('home-menu');
 const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
 let sequence=0,menus=[];
 const key=()=> 'douner.meal-cafeteria.'+campus.value;
 function show(){menu.replaceChildren();for(const m of menus.filter(m=>m.cafeteria===cafeteria.value))menu.append(node('h3',m.type),node('pre',m.text));}
 async function load(){const current=++sequence;menus=[];menu.replaceChildren();cafeteria.replaceChildren();cafeteria.disabled=true;status.textContent='오늘 식단 확인 중…';
  try{const date=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
   const response=await fetch('/api/v1/meals?month='+date.slice(0,7)+'&campus='+campus.value,{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(current!==sequence)return;
   const day=data.days.find(d=>d.date===date);menus=day?.menus||[];
   if(!menus.length){status.textContent='오늘 식단이 아직 등록되지 않았거나 수집되지 않았어요. 휴무를 뜻하지는 않아요.';return;}
   status.textContent=date+' · '+(day.stale?'오늘 갱신 여부를 확인하지 못한 자료예요.':'공식 식단표에서 수집한 메뉴예요.');
   for(const name of new Set(menus.map(m=>m.cafeteria))){const option=node('option',name);option.value=name;cafeteria.append(option);}
   try{const saved=localStorage.getItem(key());if(menus.some(m=>m.cafeteria===saved))cafeteria.value=saved;}catch{}
   cafeteria.disabled=false;show();
  }catch{if(current===sequence)status.textContent='식단을 불러오지 못했어요. 연결을 확인하고 다시 시도해 주세요.';}}
 campus.addEventListener('change',load);cafeteria.addEventListener('change',()=>{try{localStorage.setItem(key(),cafeteria.value);}catch{}show();});
 const demo=document.querySelector('.demo-home-link');if(demo&&!['localhost','127.0.0.1'].includes(location.hostname))demo.hidden=true;
 load();document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')load();});
})();
