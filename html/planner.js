'use strict';
globalThis.DongaPlanner=(()=>{
  const dayMs=86400000;
  const koreaDate=ms=>new Date(ms+9*3600000).toISOString().slice(0,10);
  function expand(entries,now){
    const today=koreaDate(now),out=[];
    for(const e of entries){
      if(!e||typeof e.name!=='string'||!/^\d{2}:\d{2}$/.test(e.time||''))continue;
      const dates=[];
      if(e.kind==='weekly'){
        for(let i=0;i<8;i++){
          const day=new Date(Date.parse(today+'T00:00:00Z')+i*dayMs),date=day.toISOString().slice(0,10);
          if(day.getUTCDay()===Number(e.weekday)&&date>=e.start&&date<=e.end)dates.push(date);
        }
      }else if(/^\d{4}-\d{2}-\d{2}$/.test(e.date||''))dates.push(e.date);
      for(const date of dates){
        const at=Date.parse(date+'T'+e.time+':00+09:00');
        if(Number.isFinite(at)&&date>=today&&at<=now+7*dayMs)out.push({...e,date,at});
      }
    }
    return out.sort((a,b)=>a.at-b.at);
  }
  function reminders(events,deadlines,now){
    return [...events.filter(e=>e.at>=now&&e.at-now<=3600000).map(e=>({id:'event:'+e.id+':'+e.at,text:e.name+' · '+e.time+' (한국 시간)'})),
      ...deadlines.filter(d=>{const delta=Date.parse(d.due_at)-now;return delta>=0&&delta<=dayMs;}).map(d=>({id:'due:'+d.url+':'+d.due_at,text:d.course+' · '+d.title+' · 24시간 이내 마감 (제출 상태 재확인)'}))];
  }
  return {koreaDate,expand,reminders};
})();
