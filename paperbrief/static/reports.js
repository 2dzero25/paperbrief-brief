// 보고서: status dots on the cards, and the report screen (route `#report/<arxiv id>`).
//
// Later tickets plug in through `ext` below (push or splice, nothing else to edit):
//   ext.links    #10: (state) => html for the header links (arXiv, PDF, GitHub)
//   ext.menu     #12: (state) => html for the items in the ⋯ menu ([다시 작성])
//   ext.failure  #8:  (state) => html under the failure line ([다시 시도], log)
//   ext.top      #9:  (report, state) => html between the hook and the rows (원문 그림)
//   ext.rows     {label, html: (report, state) => html}; #10 splices 재현 in before 한계
//   ext.after    #11: (state) => html below the report (질문 box); rendered whenever a report is shown, also under a failed 다시 작성
// `state` is the JSON of GET /api/papers/<id>/report.
import { ext as papers } from "./papers.js";

const css = document.createElement("link");
css.rel = "stylesheet";
css.href = "/static/reports.css";
document.head.append(css);

export const ext = {
  links: [],
  menu: [],
  failure: [],
  top: [],
  rows: [
    { label: "방법", html: (r) => esc(r.method) },
    { label: "결과", html: (r) => esc(r.results) },
    { label: "차이", html: (r) => esc(r.difference) },
    { label: "의미", html: (r) => esc(r.meaning) },
    { label: "한계", html: (r) => esc(r.limitations) },
  ],
  after: [],
};

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const STAGE = { PDF: "PDF 받는 중", 파싱: "파싱 중", 작성: "작성 중" };
const ACTIVE = ["대기", "진행 중"];

// "파싱 중… 0:41", or the place in the queue
function progress(s) {
  if (s.status === "대기") return `대기 중${s.queue_position ? ` · 앞에 ${s.queue_position - 1}편` : ""}`;
  return `${STAGE[s.stage] ?? s.stage}… ${clock(s.elapsed ?? 0)}`;
}

function dot(s) {
  if (!s) return "";
  if (s.status === "대기") return '<span class="run" title="대기">◐ 대기</span>';
  if (s.status === "진행 중") return `<span class="run" title="${esc(progress(s))}">◐</span>`;
  if (s.status === "완료") return '<span class="ok" title="완료">●</span>';
  if (s.status === "실패") return `<span class="bad" title="${esc(s.stage)} 실패">✕</span>`;
  return "";
}

// ---- card dots -------------------------------------------------------------------------------------------------
let states = {};
let timer = 0;

papers.side.push((p) => `<span class="rdot" data-id="${esc(p.arxiv_id)}">${dot(states[p.arxiv_id])}</span>`);

async function refreshDots() {
  clearTimeout(timer);
  states = (await (await fetch("/api/reports")).json()).reports;
  for (const el of document.querySelectorAll(".rdot")) el.innerHTML = dot(states[el.dataset.id]);
  // keep polling while the list is showing and something is queued or running
  if (!appEl.hidden && Object.values(states).some((s) => ACTIVE.includes(s.status))) timer = setTimeout(refreshDots, 1500);
}

// ---- screens ---------------------------------------------------------------------------------------------------
const appEl = document.getElementById("app");
const screen = document.createElement("main");
screen.id = "report";
screen.hidden = true;
appEl.after(screen);

let visit = 0; // bumped on every route change; a late response from an old visit is dropped

function header(s) {
  const p = s.paper;
  const day = p.published_day.slice(5).replace("-", "/");
  const meta = [p.organization, day, `▲${p.upvotes}`].filter(Boolean).map(esc).join(" · ");
  const menu = ext.menu.map((f) => f(s)).join("");
  return `<div class="rhead">
    <div class="row between"><button class="ghost js-back" type="button" aria-label="목록으로">←</button>
      <span class="row">${ext.links.map((f) => f(s)).join("")}${menu ? `<details class="menu"><summary aria-label="더보기">⋯</summary><div>${menu}</div></details>` : ""}</span></div>
    <div class="t">${esc(p.title)}</div>
    <div class="row" style="gap:6px">${p.primary_category ? `<span class="tag">${esc(p.primary_category)}</span>` : ""}<span class="muted meta">${meta}</span></div>
  </div>`;
}

// the stored report: also shown under a failed 다시 작성, which keeps the old one
function reportHtml(s) {
  const r = s.report;
  return `<div class="rbody">
      <div class="hook">${esc(r.hook)}</div>
      ${ext.top.map((f) => f(r, s)).join("")}
      <dl class="kv">${ext.rows.map((row) => `<dt>${esc(row.label)}</dt><dd>${row.html(r, s)}</dd>`).join("")}</dl>
    </div>${ext.after.map((f) => f(s)).join("")}`;
}

function body(s) {
  if (s.status === "완료" && s.report) return reportHtml(s);
  if (s.status === "실패") {
    return `<div class="status"><div class="row"><span class="bad">✕ ${esc(s.stage)} 실패</span></div>${ext.failure.map((f) => f(s)).join("")}</div>${s.report ? reportHtml(s) : ""}`;
  }
  const spin = s.status === "진행 중" ? '<span class="spin">⟳</span>' : "◐";
  return `<div class="status" role="status">${spin} ${esc(progress(s))}</div>`;
}

function paint(s) {
  screen.innerHTML = header(s) + body(s);
}

async function open(id) {
  const mine = ++visit;
  appEl.hidden = true;
  screen.hidden = false;
  screen.innerHTML = "";
  const url = `/api/papers/${encodeURIComponent(id)}/report`;
  const get = async () => (await fetch(url)).json();
  let s = await get();
  // Only a paper never asked for is started here; a 실패 report waits for [다시 시도] (report_failure.js).
  if (s.status === null && mine === visit) s = await (await fetch(url, { method: "POST" })).json();
  while (mine === visit) {
    paint(s);
    if (!ACTIVE.includes(s.status)) return;
    await new Promise((resolve) => setTimeout(resolve, 1000));
    if (mine !== visit) return;
    s = await get();
  }
}

function route() {
  const m = location.hash.match(/^#report\/(.+)$/);
  if (m) return open(decodeURIComponent(m[1]));
  visit++;
  screen.hidden = true;
  appEl.hidden = false;
  return refreshDots();
}

document.addEventListener("click", (e) => {
  if (!(e.target instanceof Element)) return;
  const card = e.target.closest("button.card[data-id]");
  if (card instanceof HTMLElement) location.hash = `#report/${card.dataset.id}`;
  else if (e.target.closest(".js-back")) location.hash = "";
});
addEventListener("hashchange", route);
route();
