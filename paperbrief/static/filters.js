// 분야 chips, 코드 toggle and ◀ ▶ over the card list (plugs into papers.js through `ext`).
import { ext, reload } from "./papers.js";

const state = { day: "", category: "", code: false };
let data = null;
const short = (c) => c.split(".").pop(); // "cs.CV" -> "CV"; the full name is the tooltip
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

ext.query = () => {
  const q = new URLSearchParams();
  if (state.day) q.set("day", state.day);
  if (state.category) q.set("category", state.category);
  if (state.code) q.set("code", "1");
  const s = q.toString();
  return s ? "?" + s : "";
};
ext.meta.unshift((p) => p.primary_category && short(p.primary_category)); // the card shows the primary category only

const bar = document.getElementById("filters");
bar.insertAdjacentHTML(
  "beforeend",
  `<span class="row" id="chips"></span><button class="chip" type="button" id="code" aria-pressed="false">코드</button>`,
);
const chips = document.getElementById("chips");
const codeBtn = document.getElementById("code");

ext.loaded.push((d) => {
  data = d;
  const all = `<button class="chip${state.category ? "" : " on"}" type="button" data-c="">전체</button>`;
  chips.innerHTML =
    all +
    d.categories
      .map(
        (c) =>
          `<button class="chip${state.category === c.category ? " on" : ""}" type="button" data-c="${esc(c.category)}" title="${esc(c.category)} · ${c.count}">${esc(short(c.category))}</button>`,
      )
      .join("");
  codeBtn.classList.toggle("on", state.code);
  codeBtn.setAttribute("aria-pressed", String(state.code));
  document.getElementById("prev").disabled = !d.prev_day;
  document.getElementById("next").disabled = !d.next_day;
});

chips.addEventListener("click", (e) => {
  const b = e.target instanceof Element && e.target.closest("[data-c]");
  if (!(b instanceof HTMLElement)) return;
  state.category = b.dataset.c ?? ""; // single select
  reload();
});
codeBtn.addEventListener("click", () => {
  state.code = !state.code;
  reload();
});
document.addEventListener("click", (e) => {
  if (!(e.target instanceof Element) || !e.target.closest(".js-reset")) return;
  state.category = "";
  state.code = false;
  reload();
});
for (const [id, key] of [["prev", "prev_day"], ["next", "next_day"]]) {
  document.getElementById(id)?.addEventListener("click", () => {
    if (!data?.[key]) return;
    state.day = data[key];
    state.category = ""; // chips differ from day to day
    reload();
  });
}
