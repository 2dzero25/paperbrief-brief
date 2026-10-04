// 질문: saved Q&A above an input, under a 완료 report. Mounted through `ext.after` of reports.js as <paper-qa>.
// A failed answer saves nothing: the text stays in the input with ✕ and [다시].
import { ext } from "./reports.js";

const css = document.createElement("link");
css.rel = "stylesheet";
css.href = "/static/questions.css";
document.head.append(css);

const el = (tag, attrs = {}, text = "") => Object.assign(document.createElement(tag), attrs, text ? { textContent: text } : {});

class PaperQA extends HTMLElement {
  connectedCallback() {
    this.id_ = this.dataset.id ?? "";
    this.url = `/api/papers/${encodeURIComponent(this.id_)}/questions`;
    this.list = el("div", { className: "qlist" });
    this.input = el("input", { id: "q", placeholder: "질문", ariaLabel: "질문", autocomplete: "off" });
    this.send = el("button", { className: "btn", type: "submit", ariaLabel: "보내기" }, "↵");
    this.note = el("div", { className: "qnote", role: "status" });
    this.retry = el("button", { className: "btn", type: "button" }, "다시");
    this.retry.hidden = true;
    this.retry.addEventListener("click", () => this.ask());
    const form = el("form", { className: "ask" });
    form.append(this.input, this.send);
    form.addEventListener("submit", (e) => (e.preventDefault(), this.ask()));
    const status = el("div", { className: "qstatus" });
    status.append(this.note, this.retry);
    this.replaceChildren(this.list, status, form);
    this.load();
  }

  async load() {
    const res = await fetch(this.url);
    if (res.ok) for (const q of (await res.json()).questions) this.add(q);
  }

  add(q) {
    const item = el("div", { className: "qa" });
    item.append(el("div", { className: "q" }, q.question), el("div", { className: "a" }, q.answer));
    this.list.append(item);
  }

  async ask() {
    const question = this.input.value.trim();
    if (!question || this.input.disabled) return;
    this.input.disabled = this.send.disabled = true;
    this.retry.hidden = true;
    this.note.className = "qnote";
    this.note.textContent = "⟳ 답 생성 중…";
    try {
      const res = await fetch(this.url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) });
      if (!res.ok) throw new Error(((await res.json().catch(() => ({}))).detail) ?? res.statusText);
      this.add(await res.json());
      this.input.value = "";
      this.note.textContent = "";
    } catch (e) {
      this.note.className = "qnote bad";
      this.note.textContent = `✕ 답 생성 실패${e instanceof Error && e.message ? `: ${e.message}` : ""}`;
      this.retry.hidden = false;
    } finally {
      this.input.disabled = this.send.disabled = false;
    }
  }
}
customElements.define("paper-qa", PaperQA);

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
ext.after.push((s) => `<paper-qa data-id="${esc(s.arxiv_id)}"></paper-qa>`);
