"use strict";
const form = document.querySelector("#chat-form");
const input = document.querySelector("#question");
const messages = document.querySelector("#messages");
const send = document.querySelector("#send");
let language = "ko";
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
      row.append(element('p', '', `첨부파일 · ${source.attachment.page}쪽`));
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
    section.append(row);
  }
  article.append(section);
}
document.querySelectorAll("[data-lang]").forEach(button => button.addEventListener("click", () => {
  language = button.dataset.lang;
  document.querySelectorAll("[data-lang]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
  input.placeholder = samples[language];
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
  busy = true; send.disabled = true;
  document.querySelector("#clear-chat").disabled = true;
  addMessage("user", question);
  input.value = ""; updateCount();
  const pending = addMessage("assistant", "답변 생성 중…");
  pending.setAttribute("aria-busy", "true");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch("/api/v1/ask", {method:"POST", headers:{"Content-Type":"application/json"},body:JSON.stringify({question,language:selectedLanguage,category:document.querySelector("#category").value || null,search_mode:document.querySelector("#search-mode").value,conversation_context:window.StudentUI?.context(conversationContext) || conversationContext}),signal:controller.signal});
    if (!response.ok) throw new Error(response.status === 429 ? "요청이 많습니다. 잠시 후 다시 질문해 주세요." : "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    const data = await response.json();
    if (typeof data.answer !== "string") throw new Error("답변을 읽지 못했습니다. 다시 시도해 주세요.");
    conversationContext = data.conversation_context || null;
    pending.querySelector(".bubble").textContent = data.answer;
    pending.querySelector(".bubble").lang = selectedLanguage;
    addSources(pending, data.sources);
    const reportButton = window.StudentUI?.reportButton(question, data);
    if (reportButton) pending.append(reportButton);
    if (typeof data.meal_calendar === 'string' && /^meals\.html\?month=20\d{2}-\d{2}&campus=[12]$/.test(data.meal_calendar)) {
      const calendarLink = element('a', '', '월별 식단 보기');
      calendarLink.href = data.meal_calendar;
      pending.append(calendarLink);
    }
  } catch (error) {
    pending.querySelector(".bubble").textContent = error.name === "AbortError" ? "응답 시간이 길어지고 있습니다. 잠시 후 다시 시도해 주세요." : (error instanceof TypeError ? "네트워크 연결을 확인하고 다시 시도해 주세요." : error.message);
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
