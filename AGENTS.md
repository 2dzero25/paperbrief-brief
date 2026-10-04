# AGENTS.md

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`2dzero25/paperbrief-brief`), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.

## Commands

Python 3.12 + [uv](https://docs.astral.sh/uv/). Run from the repo root.

- Install: `uv sync` (one lock for Windows, Linux x86_64, Linux aarch64; downloads several GB of torch/MinerU)
- Test: `uv run pytest` (offline; no network, GPU or OpenAI)
- Typecheck: `uv run pyright`
- Run: `run.bat` (Windows) / `run.sh` (Linux); both start the server on `127.0.0.1` (`PAPERBRIEF_PORT`, default 8765) and open the browser
- Settings: copy `.env.example` to `.env`; never commit `.env`

## App layout (`paperbrief/`)

- `create_app(settings, boundaries=None)` in `app.py`. The four external boundaries are injected: `hf.HFClient`, `arxiv.ArxivClient`, `llm.LLMClient`, `parser.Parser` (each a small `Protocol` in its own module, bundled as `boundaries.Boundaries`). Each boundary module owns its `live(settings)` and `offline(settings)` factory; `PAPERBRIEF_OFFLINE=1` uses `offline`. Routes never import a real client.
- Routes: one module per feature in `routes/`, each with a module-level `router`; `create_app` registers every module found there. Get settings, boundaries and the DB through `deps.SettingsDep`, `BoundariesDep`, `DbDep`.
- 보고서: `reports.py` is the single FIFO worker (`STAGES` = PDF → 파싱 → 작성, results kept under `<data dir>/papers/<id>/`), `routes/reports.py` its API, `report_prompt.py` the prompt, `static/reports.js` the card dots and report screen (`ext.*` insertion points listed at its top). `Report` in `llm.py` is the stored JSON: only add fields, with defaults. Tests fake arxiv.org by setting `app.state.pdf_http` to an `httpx.Client(transport=MockTransport(...))`.
- Tests: only through the HTTP API with the `make_client` fixture (`tests/conftest.py`) and the fakes in `tests/fakes.py`.
- DB: `migrations/NNNN_name.sql`, next free number, add-only (ADR-0001). Static page: `static/` (vanilla JS modules, imported from `app.js`).

## Check current docs with MCP (`.mcp.json`)

Do not rely on memory for these; look them up first.

| Target | MCP |
|---|---|
| FastAPI, httpx, pydantic, pytest | Context7 |
| MinerU (`opendatalab/MinerU`) | DeepWiki |
| OpenAI API, uv | mcpdoc (`llms.txt`) |

Code navigation: use Serena or the pyright LSP before `grep`. Fall back to `grep` only for plain text (docs, config, strings).

The pyright LSP plugin (`pyright-lsp@claude-plugins-official`) is enabled in `.claude/settings.json`. Each collaborator installs it once with `claude plugin install pyright-lsp@claude-plugins-official --scope project`, and it needs `pyright-langserver` on `PATH` (after `uv sync` it is in `.venv`; activate the venv or `uv tool install pyright`).

## Windows and Ubuntu

All code must run on both.

- Build paths with `pathlib.Path`, never hardcoded `\` or `/` strings.
- Read and write text with `encoding="utf-8"` explicitly.
- Run subprocesses with an argument list and no `shell=True`; do not assume `bash`, `sh` or `.exe` names.
- Put data under the OS data dir (Windows `%LOCALAPPDATA%\PaperBrief`, Linux `~/.local/share/PaperBrief`), never inside the repo.
- Do not use `fork`-only multiprocessing, `os.getuid`, `signal.SIGKILL` or other POSIX-only or Windows-only APIs without a guard.
- Torch, torchvision and `override-dependencies` live in `pyproject.toml`; do not pin per-OS packages anywhere else.

## Code Review Rules

- Answer in korean.
- Flag any API key, token, or password written in source code; secrets belong in `.env` only.
- Flag schema changes to the local SQLite DB that would drop or rewrite existing user rows.
- Flag any new parser/OCR model whose Hugging Face parameter count exceeds 7B.

