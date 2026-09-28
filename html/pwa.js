'use strict';
(() => {
  const make=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;return node;};
  const installed=()=>matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  if(matchMedia('(pointer: coarse)').matches){
    const hint=document.querySelector('.composer .micro');
    if(hint?.firstChild?.nodeType===Node.TEXT_NODE)hint.firstChild.textContent='보내기 버튼으로 전송 ';
  }
  const status=document.querySelector('#install-status');
  const installButton=document.querySelector('#install-app');
  const network=make('p','오프라인 상태입니다. 새 답변과 식단 조회에는 인터넷 연결이 필요합니다.');
  network.className='network-notice';network.setAttribute('role','status');network.hidden=true;
  document.querySelector('.site-header')?.after(network);
  const networkState=()=>{network.hidden=navigator.onLine;};
  window.addEventListener('online',networkState);window.addEventListener('offline',networkState);networkState();
  const nav=make('nav','');nav.className='mobile-nav';nav.setAttribute('aria-label','주요 메뉴');
  for(const [title,href] of [['홈','index.html'],['질문','chat.html'],['식단','meals.html'],['내 정보','chat.html#student-settings']]){
    const link=make('a',title);link.href=href;
    if((location.pathname.endsWith(href) || (location.pathname==='/' && href==='index.html')) && !href.includes('#'))link.setAttribute('aria-current','page');
    nav.append(link);
  }
  document.body.append(nav);
  if(!document.querySelector('.site-header a[href="account.html"]')){
    const link=make('a','내 LMS');link.href='account.html';link.className='install-link';document.querySelector('.site-header')?.append(link);
  }
  if(!document.querySelector('.site-header a[href="install.html"]')){
    const link=make('a','앱 설치');link.href='install.html';link.className='install-link';document.querySelector('.site-header')?.append(link);
  }
  const showSettings=()=>{
    if(location.hash==='#student-settings'){
      const panel=document.querySelector('#student-settings');
      panel?.querySelector('details.student-panel')?.setAttribute('open','');
      panel?.scrollIntoView();
    }
  };
  window.addEventListener('hashchange',showSettings);showSettings();
  let prompt=null;
  function installationState(){
    if(!status)return;
    if(installed())status.textContent='홈 화면에서 앱으로 실행 중입니다.';
    else if(!window.isSecureContext)status.textContent='현재 주소에서는 앱 설치를 지원하지 않습니다. 휴대폰에서는 HTTPS 주소로 접속해 주세요.';
    else status.textContent='아래 휴대폰별 안내를 따라 홈 화면에 추가하세요. 설치 버튼은 지원되는 브라우저에서 표시됩니다.';
    if(installButton)installButton.hidden=installed() || !prompt;
  }
  window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();prompt=event;installationState();});
  window.addEventListener('appinstalled',()=>{prompt=null;if(status)status.textContent='설치했습니다. 홈 화면에서 douner를 열어 보세요.';if(installButton)installButton.hidden=true;});
  installButton?.addEventListener('click',async()=>{
    if(!prompt)return;
    const current=prompt;prompt=null;installButton.hidden=true;
    try { await current.prompt(); const choice=await current.userChoice;if(status)status.textContent=choice.outcome==='accepted'?'설치를 요청했습니다. 홈 화면을 확인해 주세요.':'설치를 취소했습니다. 웹에서도 계속 사용할 수 있습니다.'; }
    catch { installationState(); }
  });
  installationState();
  if('serviceWorker' in navigator && window.isSecureContext){
    let requestedUpdate=false;
    navigator.serviceWorker.addEventListener('controllerchange',()=>{if(requestedUpdate)location.reload();});
    navigator.serviceWorker.register('/sw.js',{scope:'/',updateViaCache:'none'}).then(registration=>{
      const offerUpdate=()=>{
        if(!registration.waiting || document.querySelector('.update-notice'))return;
        const box=make('div','새 버전이 있습니다. 새로고침하면 현재 대화가 초기화됩니다. ');box.className='update-notice';
        const button=make('button','새로고침');button.type='button';
        button.addEventListener('click',()=>{
          if(document.querySelector('#send')?.disabled){button.textContent='답변 완료 후 다시 눌러 주세요';return;}
          requestedUpdate=true;registration.waiting?.postMessage({type:'APPLY_UPDATE'});
        });box.append(button);document.querySelector('.site-header')?.after(box);
      };
      offerUpdate();registration.addEventListener('updatefound',()=>{registration.installing?.addEventListener('statechange',offerUpdate);});
    }).catch(()=>{if(status)status.textContent='오프라인 화면 준비에 실패했습니다. 연결 상태를 확인하고 새로고침해 주세요. 웹 기능은 계속 사용할 수 있습니다.';});
  }
})();
