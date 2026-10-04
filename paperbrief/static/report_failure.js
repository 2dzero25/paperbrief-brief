// 보고서 실패 (#8): under the "✕ <단계> 실패" line of the report screen, [다시 시도] and the log that can be opened.
import { ext } from "./reports.js";

const css = document.createElement("link");
css.rel = "stylesheet";
css.href = "/static/report_failure.css";
document.head.append(css);

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

ext.failure.push(
  (s) => `<div class="row fail">
    <button class="btn js-retry" type="button" data-id="${esc(s.arxiv_id)}">다시 시도</button>
    <button class="ghost js-log" type="button" aria-expanded="false" aria-controls="logbox">로그 ▸</button>
  </div>
  <pre id="logbox" class="logbox" hidden>${esc(s.error_log)}</pre>`,
);

document.addEventListener("click", async (e) => {
  if (!(e.target instanceof Element)) return;
  const log = e.target.closest(".js-log");
  if (log instanceof HTMLElement) {
    const box = document.getElementById("logbox");
    if (box) box.hidden = !box.hidden;
    log.setAttribute("aria-expanded", String(!!box && !box.hidden));
    log.textContent = box && !box.hidden ? "로그 ▾" : "로그 ▸";
    return;
  }
  const retry = e.target.closest(".js-retry");
  if (retry instanceof HTMLButtonElement) {
    retry.disabled = true;
    await fetch(`/api/papers/${encodeURIComponent(retry.dataset.id ?? "")}/report`, { method: "POST" });
    dispatchEvent(new Event("hashchange")); // the report screen opens again and follows the new run
  }
});
