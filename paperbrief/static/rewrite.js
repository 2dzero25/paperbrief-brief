// 다시 작성 (#12): the ⋯ menu item of a 완료 report. Only a click starts it; the screen then follows the queue like any report.
import { ext } from "./reports.js";

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

ext.menu.push((s) => (s.status === "완료" ? `<button class="ghost js-rewrite" type="button" data-id="${esc(s.arxiv_id)}">다시 작성</button>` : ""));

document.addEventListener("click", async (e) => {
  const b = e.target instanceof Element ? e.target.closest(".js-rewrite") : null;
  if (!(b instanceof HTMLButtonElement)) return;
  b.disabled = true;
  await fetch(`/api/papers/${encodeURIComponent(b.dataset.id ?? "")}/report/rewrite`, { method: "POST" });
  dispatchEvent(new Event("hashchange")); // the report screen opens again and follows the new run
});
