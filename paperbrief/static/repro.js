// 재현 체크 (#10): header links, and the 재현 row (✓/✗/? badges, click one to see its 근거) before 한계.
import { ext } from "./reports.js";

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const ITEMS = [["code", "코드"], ["weights", "가중치"], ["data", "데이터"], ["gpu", "GPU"], ["license", "라이선스"]];
const MARK = { 공개: ["ok", "✓"], 비공개: ["bad", "✗"], "명시 없음": ["run", "?"] };

ext.links.push((s) =>
  (s.links ?? []).map((l) => `<a class="ghost" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)}</a>`).join(""),
);

const row = {
  label: "재현",
  html: (r) => {
    if (!r.repro) return '<span class="muted">명시 없음</span>';
    const badges = ITEMS.map(([key, name]) => {
      const [cls, mark] = MARK[r.repro[key].verdict];
      return `<button type="button" class="${cls}" aria-expanded="false" data-why="${esc(r.repro[key].evidence)}">${mark} ${name}</button>`;
    }).join("");
    return `<div class="repro">${badges}</div><div class="why" aria-live="polite"></div>`;
  },
};
ext.rows.splice(ext.rows.findIndex((x) => x.label === "한계"), 0, row);

document.addEventListener("click", (e) => {
  const b = e.target instanceof Element ? e.target.closest(".repro button") : null;
  if (!(b instanceof HTMLElement)) return;
  const box = b.closest("dd")?.querySelector(".why");
  const open = b.getAttribute("aria-expanded") !== "true";
  for (const x of b.parentElement?.children ?? []) x.setAttribute("aria-expanded", "false");
  b.setAttribute("aria-expanded", String(open));
  if (box) box.textContent = open ? b.dataset.why ?? "" : "";
});
