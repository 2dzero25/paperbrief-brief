// KO/EN tabs: switch the one-line summary on every card (plugs into papers.js through `ext.summary`).
import { ext, reload } from "./papers.js";

let lang = "ko";

// KO falls back to EN while a card has no KO summary yet, so a line is never empty
ext.summary = (p) => (lang === "ko" && p.summary_ko) || p.summary_en;

document.getElementById("filters")?.insertAdjacentHTML(
  "beforeend",
  `<span class="row" id="lang"><button class="chip on" type="button" data-l="ko" aria-pressed="true">KO</button><button class="chip" type="button" data-l="en" aria-pressed="false">EN</button></span>`,
);
document.getElementById("lang")?.addEventListener("click", (e) => {
  const b = e.target instanceof Element && e.target.closest("[data-l]");
  if (!(b instanceof HTMLElement) || b.dataset.l === lang) return;
  lang = b.dataset.l ?? "ko";
  for (const c of document.querySelectorAll("#lang .chip")) {
    const on = c === b;
    c.classList.toggle("on", on);
    c.setAttribute("aria-pressed", String(on));
  }
  reload();
});
