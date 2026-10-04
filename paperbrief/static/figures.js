// 원문 그림 (#9): the picked figures with their captions after the hook, or "그림 없음". Panels of one figure share a caption.
import { ext } from "./reports.js";

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

ext.top.push((_report, state) => {
  const figs = state.figures ?? [];
  if (!figs.length) return '<div class="nofig muted">그림 없음</div>';
  return figs
    .map(
      (f) => `<figure class="fig">
        <div class="panels">${f.images.map((src) => `<img src="${esc(src)}" alt="${esc(f.caption)}" loading="lazy">`).join("")}</div>
        <figcaption class="cap">${esc(f.caption)}</figcaption>
      </figure>`,
    )
    .join("");
});
