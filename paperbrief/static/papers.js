// 수집 + the card list of the most recent 발표일.
//
// Later tickets plug in through `ext` (set a property or push to an array, then call `reload()`) and the fixed DOM below:
//   #filters  empty row in the toolbar (#5 puts its category chips / 코드 toggle / KO-EN tabs here)
//   #list     one `button.card[data-id]` per paper; #7 listens for clicks on it
//   .card .side  right-hand corner of a card (</> flag, then whatever `ext.side` returns)
const css = document.createElement("link");
css.rel = "stylesheet";
css.href = "/static/papers.css";
document.head.append(css);

export const ext = {
  query: () => "", // #5: extra query string for /api/papers, e.g. "?category=cs.CL&code=1"
  summary: (p) => p.summary_en, // #6: pick KO or EN one-line summary
  meta: [(p) => p.organization], // #5: push (p) => category label in front; falsy results are skipped
  side: [], // #7: (p) => html string, e.g. the report status dot
};

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const app = document.getElementById("app");
app.innerHTML = `
  <div class="top">
    <div class="row between"><span class="date" id="day"></span><span class="row"><span class="tag" id="recent" hidden>최근</span><button class="btn primary js-collect" type="button" data-label="수집">수집</button></span></div>
    <div class="row" id="filters"></div>
  </div>
  <div id="alert"></div>
  <div id="list"></div>`;
const $ = (id) => document.getElementById(id);

let running = false;
let polled = false;

function dayLabel(iso, count) {
  const [y, m, d] = iso.split("-").map(Number);
  const wd = WEEKDAYS[new Date(y, m - 1, d).getDay()];
  return `${String(m).padStart(2, "0")}/${String(d).padStart(2, "0")} (${wd}) · ${count}`;
}

function card(p) {
  const meta = ext.meta.map((f) => f(p)).filter(Boolean).map(esc).join(" · ");
  const side = (p.has_code ? '<span title="등록 코드">&lt;/&gt;</span>' : "") + ext.side.map((f) => f(p)).join("");
  return `<button class="card" type="button" data-id="${esc(p.arxiv_id)}"><span class="up">▲${p.upvotes}</span><span class="t">${esc(p.title)}</span>
    <span class="side">${side}</span><span class="s">${esc(ext.summary(p))}</span><span class="m">${meta}</span></button>`;
}

function paintButtons() {
  for (const b of document.querySelectorAll(".js-collect")) {
    b.disabled = running;
    b.innerHTML = running ? '<span class="spin" aria-label="수집 중">⟳</span>' : b.dataset.label;
  }
}

export async function reload() {
  const res = await fetch("/api/papers" + ext.query());
  const data = await res.json();
  $("day").textContent = data.day ? dayLabel(data.day, data.count) : "";
  $("recent").hidden = !(data.day && data.recent);
  $("list").innerHTML = data.day
    ? data.papers.map(card).join("")
    : '<div class="empty"><span>논문 없음</span><button class="btn primary js-collect" type="button" data-label="수집">수집</button></div>';
  paintButtons();
}

function showError(error) {
  $("alert").innerHTML = error
    ? `<div class="alert"><span>수집 실패</span><button class="btn js-collect" type="button" data-label="다시">다시</button></div>`
    : "";
  paintButtons();
}

async function poll() {
  const state = await (await fetch("/api/collect")).json();
  const refresh = !state.running && (running || !polled); // a run just ended, or first look: the list may be stale
  polled = true;
  running = state.running;
  showError(state.running ? null : state.error);
  paintButtons();
  if (state.running) setTimeout(poll, 1000);
  else if (refresh) await reload(); // finished: show the new list (on failure the old one stays)
}

document.addEventListener("click", async (e) => {
  if (!(e.target instanceof Element) || !e.target.closest(".js-collect")) return;
  if (running) return;
  running = true;
  showError(null);
  await fetch("/api/collect", { method: "POST" });
  poll();
});

reload();
poll();
