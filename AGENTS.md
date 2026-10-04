# AGENTS.md

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`2dzero25/paperbrief-brief`), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.

## Code Review Rules

- Answer in korean.
- Flag any API key, token, or password written in source code; secrets belong in `.env` only.
- Flag schema changes to the local SQLite DB that would drop or rewrite existing user rows.
- Flag any new parser/OCR model whose Hugging Face parameter count exceeds 7B.

