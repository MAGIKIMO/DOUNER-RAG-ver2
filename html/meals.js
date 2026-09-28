"use strict";
const monthInput=document.querySelector('#meal-month');
const campusInput=document.querySelector('#meal-campus');
const dayBody=document.querySelector('#meal-days');
const statusLine=document.querySelector('#meal-status');
let mealData=null, selectedDate=null, sequence=0;
const koreaToday=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const params=new URLSearchParams(location.search);
monthInput.value=/^20\d{2}-(0[1-9]|1[0-2])$/.test(params.get('month')||'')?params.get('month'):koreaToday().slice(0,7);
let savedCampus='2';
try { const profile=JSON.parse(localStorage.getItem('donga.student.v1')); if(['1','2'].includes(profile?.campus))savedCampus=profile.campus; } catch { /* Optional local preference. */ }
campusInput.value=['1','2'].includes(params.get('campus'))?params.get('campus'):savedCampus;
function node(tag,text,className){const el=document.createElement(tag);el.textContent=text;if(className)el.className=className;return el;}
function selectDay(day){
  selectedDate=day.date;
  dayBody.querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.date===day.date)));
  document.querySelector('#meal-heading').textContent=`${day.date} · ${mealData.campus_name}`;
  const content=document.querySelector('#meal-content');content.replaceChildren();
  if(day.checked_at)content.append(node('p',`마지막 확인: ${new Date(day.checked_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})} (한국 시간)`,'micro'));
  if(day.stale)content.append(node('p','오늘 갱신은 아직 확인되지 않았습니다. 이전 수집 자료입니다.','micro'));
  if(!day.menus.length)content.append(node('p',day.status==='not_collected'?'아직 수집하지 못한 날짜입니다.':'공식 식단표에 등록된 메뉴가 없습니다. 휴무 여부는 확인되지 않았습니다.'));
  for(const item of day.menus){const section=node('section','','meal-menu');section.append(node('h3',`${item.cafeteria} · ${item.type}`),node('pre',item.text));content.append(section);}
  const link=node('a','공식 식단표 보기');link.href=day.url;link.target='_blank';link.rel='noopener noreferrer';content.append(link);
}
function render(data){
  mealData=data;dayBody.replaceChildren();
  document.querySelector('#meal-caption').textContent=`${data.month} · ${data.campus_name}`;
  const [year,month]=data.month.split('-').map(Number);
  const offset=(new Date(Date.UTC(year,month-1,1)).getUTCDay()+6)%7;
  let row=document.createElement('tr');
  for(let i=0;i<offset;i++)row.append(document.createElement('td'));
  data.days.forEach((day,index)=>{
    if((offset+index)%7===0&&row.children.length){dayBody.append(row);row=document.createElement('tr');}
    const cell=document.createElement('td');const button=node('button',String(index+1));button.type='button';
    const label=day.status==='published'?'메뉴 있음':day.status==='not_published'?'미등록':'수집 대기';
    button.append(node('small',day.status==='published'?'등록':day.status==='not_published'?'미등록':'대기'));button.dataset.date=day.date;button.dataset.today=String(day.date===data.today);
    button.setAttribute('aria-label',`${day.date}, ${label}`);button.addEventListener('click',()=>selectDay(day));cell.append(button);row.append(cell);
  });
  while(row.children.length<7)row.append(document.createElement('td'));dayBody.append(row);
  const count=data.days.filter(day=>day.status==='published').length;
  statusLine.textContent=`${count}일분의 메뉴가 있습니다. `+({running:'자료를 갱신 중입니다.',partial:'일부 날짜 갱신에 실패했습니다. 기존 자료는 유지됩니다.',waiting:'첫 수집을 기다리고 있습니다.',ok:'최근 수집 작업을 완료했습니다.'}[data.sync_status]||'');
  selectDay(data.days.find(day=>day.date===selectedDate)||data.days.find(day=>day.date===data.today)||data.days[0]);
}
async function load(){
  const id=++sequence;statusLine.textContent='식단을 불러오는 중입니다.';
  try{
    const response=await fetch(`/api/v1/meals?month=${encodeURIComponent(monthInput.value)}&campus=${campusInput.value}`,{signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw new Error('식단을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
    const data=await response.json();if(id===sequence){render(data);history.replaceState(null,'',`?month=${data.month}&campus=${data.campus}`);}
  }catch(error){if(id===sequence){mealData=null;dayBody.replaceChildren();document.querySelector('#meal-content').replaceChildren();document.querySelector('#meal-heading').textContent='식단을 불러오지 못했습니다.';statusLine.textContent=error.name==='TimeoutError'?'연결 시간이 초과되었습니다. 다시 불러와 주세요.':error.message;}}
}
document.querySelector('#meal-filter').addEventListener('submit',event=>{event.preventDefault();load();});
campusInput.addEventListener('change',load);
document.querySelector('#meal-today').addEventListener('click',()=>{monthInput.value=koreaToday().slice(0,7);selectedDate=koreaToday();load();});
load();
