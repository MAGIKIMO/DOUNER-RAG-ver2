"use strict";
const form = document.querySelector("#chat-form");
const input = document.querySelector("#question");
const messages = document.querySelector("#messages");
const send = document.querySelector("#send");
let language = "auto";
let languageSelected = false;
let busy = false;
let conversationContext = null;
const samples = {ko:"졸업하려면 어떤 조건을 확인해야 해?",ja:"日本語で留学生向けのお知らせを教えてください",en:"Please summarize the graduation requirements",zh:"请告诉我留学生相关通知"};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function updateCount() { document.querySelector("#char-count").textContent = `${input.value.length} / 2,000`; }
function scrollMessages() { messages.scrollTop = messages.scrollHeight; }
function addMessage(role, text) {
  document.querySelector("#welcome")?.remove();
  const article = element("article", `message ${role}`);
  article.append(element("p", "message-label", role === "user" ? "나의 질문" : "douner"));
  article.append(element("div", "bubble", text));
  messages.append(article);
  scrollMessages();
  return article;
}
function addSources(article, sources) {
  if (!Array.isArray(sources) || !sources.length) return;
  const section = element("section", "references");
  section.append(element("h3", "", `참고 자료 · ${sources.length}건`));
  for (const source of sources) {
    let url;
    try { url = new URL(source.url); } catch { continue; }
    if (!["https:", "http:"].includes(url.protocol)) continue;
    const row = element("div", "reference");
    const link = element("a", "", `[${source.id}] ${source.title} ↗`);
    link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
    row.append(link);
    row.append(element("p", "", `${source.category} · ${source.published_at ? source.published_at.slice(0,10) : "게시일 미표기"}`));
    if (source.checked_at) {
      const checked = new Date(source.checked_at);
      if (!Number.isNaN(checked.getTime())) row.append(element('p', 'micro', `자료 수집 확인: ${checked.toLocaleString('ko-KR', {timeZone: 'Asia/Seoul'})} (한국 시간)`));
    }
    row.append(element("p", "", url.href));
    if (source.attachment) {
      row.append(element('p', '', source.attachment.page ? `첨부파일 · ${source.attachment.page}쪽` : '첨부파일 · 질문에 관련된 내용 발췌'));
      try {
        const parentURL = new URL(source.attachment.parent_url);
        if (['https:', 'http:'].includes(parentURL.protocol)) {
          const parentLink = element('a', '', '첨부파일이 게시된 공지 보기');
          parentLink.href = parentURL.href; parentLink.target = '_blank'; parentLink.rel = 'noopener noreferrer'; row.append(parentLink);
        }
      } catch { /* Invalid optional parent URL. */ }
    }
    const saveButton = window.StudentUI?.sourceButton(source);
    if (saveButton && source.source_type !== "meal") row.append(saveButton);
    if(source.source_type==='notice' && Number.isInteger(source.source_id)){
      const taskLink=element('a','','내 할 일 만들기 →');taskLink.href='tasks.html?notice='+source.source_id;row.append(taskLink);
    }
    section.append(row);
  }
  article.append(section);
}
document.querySelectorAll("[data-lang]").forEach(button => button.addEventListener("click", () => {
  language = button.dataset.lang;
  languageSelected = true;
  document.querySelectorAll("[data-lang]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
  input.placeholder = samples[language] || samples.ko;
}));
document.querySelectorAll("[data-question]").forEach(button => button.addEventListener("click", () => {
  if (busy) return;
  input.value = button.dataset.question; updateCount(); input.focus();
}));
input.addEventListener("input", updateCount);
input.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && !matchMedia('(pointer: coarse)').matches) {
    event.preventDefault(); if (!busy) form.requestSubmit();
  }
});
document.querySelector("#clear-chat").addEventListener("click", () => {
  if (busy) return;
  messages.replaceChildren(); input.value = ""; updateCount();
  conversationContext = null;
  addMessage("assistant", "새 대화를 시작해요. 이전 대화는 초기화했습니다. 저장한 기본 정보는 유지됩니다."); input.focus();
});
form.addEventListener("submit", async event => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question || busy) return;
  const selectedLanguage = language;
  const uiLanguage = selectedLanguage === 'auto' ? (/[ぁ-んァ-ン]/.test(question) ? 'ja' : /[가-힣]/.test(question) ? 'ko' : /[一-龥]/.test(question) ? 'zh' : /[a-z]/i.test(question) ? 'en' : 'ko') : selectedLanguage;
  const notices = {
    ko:['답변 생성 중…','요청이 많습니다. 잠시 후 다시 질문해 주세요.','서버에 연결하지 못했습니다. 다시 시도해 주세요.','답변을 읽지 못했습니다.','응답 시간이 길어지고 있습니다. 다시 시도해 주세요.','네트워크 연결을 확인해 주세요.','월별 식단 보기'],
    en:['Generating an answer…','Too many requests. Please try again shortly.','Unable to reach the server. Please try again.','Unable to read the answer.','The request timed out. Please try again.','Please check your network connection.','View monthly menus'],
    ja:['回答を作成中…','リクエストが集中しています。しばらくしてから再度お試しください。','サーバーに接続できません。再度お試しください。','回答を読み取れませんでした。','応答がタイムアウトしました。再度お試しください。','ネットワーク接続をご確認ください。','月間メニューを見る'],
    zh:['正在生成回答…','请求过多，请稍后重试。','无法连接服务器，请重试。','无法读取回答。','请求超时，请重试。','请检查网络连接。','查看月度菜单']
  }[uiLanguage];
  busy = true; send.disabled = true;
  document.querySelector("#clear-chat").disabled = true;
  addMessage("user", question);
  input.value = ""; updateCount();
  const pending = addMessage("assistant", notices[0]);
  pending.setAttribute("aria-busy", "true");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  try {
    const options = {method:"POST", headers:{"Content-Type":"application/json"},body:JSON.stringify({question,language:selectedLanguage,category:document.querySelector("#category").value || null,search_mode:document.querySelector("#search-mode").value,conversation_context:window.StudentUI?.context(conversationContext) || conversationContext}),signal:controller.signal};
    let response = await fetch('/api/v1/ask/stream',options);
    if(response.status===404)response=await fetch('/api/v1/ask',options);
    if (!response.ok) throw new Error(response.status === 429 ? notices[1] : notices[2]);
    let partial='';
    const phases={ko:['질문을 이해하고 있어요…','학교 자료를 찾고 있어요…','근거를 읽고 답변하는 중…'],en:['Understanding your question…','Searching school documents…','Writing an answer from the sources…'],ja:['質問を確認しています…','学校の資料を検索中…','資料に基づいて回答を作成中…'],zh:['正在理解问题…','正在检索学校资料…','正在根据资料生成回答…']}[uiLanguage];
    const data = response.headers.get('content-type')?.includes('application/x-ndjson') ? await readAnswerStream(response,event=>{
      if(event.type==='reset'){partial='';pending.querySelector('.bubble').textContent=notices[0];}
      if(event.type==='phase'&&!partial)pending.querySelector('.bubble').textContent=phases[event.phase==='query_preparation'?0:event.phase==='generation'?2:1];
      if(event.type==='answer_delta'){partial+=event.text;pending.querySelector('.bubble').textContent=partial;scrollMessages();}
    }) : await response.json();
    if (typeof data.answer !== "string") throw new Error(notices[3]);
    conversationContext = data.conversation_context || null;
    pending.querySelector(".bubble").textContent = data.answer;
    pending.querySelector(".bubble").lang = data.answer_language || uiLanguage;
    if (Array.isArray(data.source_excerpts)) {
      const label = {ko:'추출 원문 보기',en:'Show extracted source',ja:'抽出した原文を表示',zh:'查看提取原文'}[data.answer_language || uiLanguage] || '추출 원문 보기';
      for (const excerpt of data.source_excerpts.slice(0,2)) {
        if (typeof excerpt.text !== 'string') continue;
        const details = element('details','source-preview');
        details.append(element('summary','',label + ' · ' + (excerpt.title || '')));
        details.append(element('pre','',excerpt.text.slice(0,3000)));
        pending.append(details);
      }
    }
    addSources(pending, data.sources);
    const reportButton = window.StudentUI?.reportButton(question, data);
    if (reportButton) pending.append(reportButton);
    if (typeof data.meal_calendar === 'string' && /^meals\.html\?month=20\d{2}-\d{2}&campus=[12]$/.test(data.meal_calendar)) {
      const calendarLink = element('a', '', notices[6]);
      calendarLink.href = data.meal_calendar;
      pending.append(calendarLink);
    }
  } catch (error) {
    pending.querySelector(".bubble").textContent = error.name === "AbortError" ? notices[4] : (error instanceof TypeError ? notices[5] : error.status===429?notices[1]:notices[2]);
    input.value = question; updateCount();
  } finally {
    clearTimeout(timer); pending.removeAttribute("aria-busy"); busy = false; send.disabled = false;
    document.querySelector("#clear-chat").disabled = false; scrollMessages(); input.focus();
  }
});
async function checkStatus() {
  const status = document.querySelector("#system-status");
  status.textContent = "연결 확인 중…";
  try {
    const response = await fetch("/api/v1/heartbeat", {signal:AbortSignal.timeout(8000)});
    if (!response.ok) throw new Error();
    const data = await response.json();
    status.textContent = data.status === "ok" ? "문서 검색 준비됨 · AI 응답은 요청 시 확인" : data.components?.index === "empty" ? "수집 및 문서 색인이 필요합니다" : "일부 서비스 점검이 필요합니다";
  } catch { status.textContent = "서버 연결을 확인해 주세요"; }
}
document.querySelector("#refresh-status").addEventListener("click", checkStatus);
checkStatus();

async function loadCategories() {
  try {
    const response = await fetch("/api/v1/categories");
    if (!response.ok) return;
    const data = await response.json();
    const select = document.querySelector("#category");
    for (const row of data.categories || []) {
      const option = element("option", "", `${row.name} (${row.count})`);
      option.value = row.name; select.append(option);
      if (/학과|학부/.test(row.name)) { const item = element("option", "", row.name); item.value = row.name; document.querySelector("#department-list")?.append(item); }
    }
  } catch { /* The existing chat still works if scope discovery is unavailable. */ }
}
loadCategories();
document.querySelector("#category").addEventListener("change", () => { conversationContext = null; });
document.querySelector("#search-mode").addEventListener("change", () => { conversationContext = null; });

window.addEventListener("student-profile-changed", () => { conversationContext = null; });
