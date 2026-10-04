"""그림 후보 of a parsed paper, cut from MinerU's output folder (brief.md "MinerU 출력").

`structured_content.json` is `{"pages": [{"blocks": [{"type", "captions": [{"content"}], "image_source"}]}]}`; no block
has type `Figure`. A 그림 후보 is a block of type `image`/`chart` with a caption starting `Figure` (a `chart` may carry a
fake caption before it; a table's `image_source` is not a figure) whose image file really exists. MinerU splits a
multi-panel figure into several blocks and puts the caption on the last one only, so the `image`/`chart` blocks right
before a captioned block (same page, nothing else in between, no `Figure` caption of their own) are its panels.
File names are never built: only the `image_source` path is followed, and only inside the parsed folder.
Ids are `fig1`, `fig2`, ... in document order. The JSON is not trusted in shape: odd parts are skipped.
"""
import html
import json
import re
from pathlib import Path

from paperbrief.parser import FigureCandidate, ParseResult

MAX_PANELS = 8  # the nearest ones to the caption when a run is longer
MAX_MENTIONS = 5  # sentences handed to the model per figure
MAX_PICK = 2


def _caption(block: dict) -> str | None:
    captions = block.get("captions")
    contents = [c.get("content") for c in captions if isinstance(c, dict)] if isinstance(captions, list) else []
    caption = next((c.strip() for c in contents if isinstance(c, str) and c.strip().startswith("Figure")), None)
    return html.unescape(caption) if caption else None  # MinerU writes `<` as `&lt;`; the page escapes text itself


def inside(root: Path, source: object) -> Path | None:
    """The existing file `source` names under `root`, or None (also for `../` escapes)."""
    if not isinstance(source, str):
        return None
    try:
        path = (root / source).resolve()
        return path if path.is_relative_to(root.resolve()) and path.is_file() else None
    except (OSError, ValueError):
        return None


def _mentions(markdown: str, caption: str) -> list[str]:
    number = re.match(r"Figure\s*(\d+)", caption)
    if not number:
        return []
    cite = re.compile(rf"\b(?:Figure|Fig\.)\s*{number[1]}(?!\d)")
    is_caption = re.compile(rf"Figure\s*{number[1]}\s*[:.]")
    sentences = (s.strip() for line in markdown.splitlines() for s in re.split(r"(?<=[.!?])\s+", line))
    found = [s for s in sentences if cite.search(s) and not is_caption.match(s)]
    return found[:MAX_MENTIONS]


def extract(parsed: Path, markdown: str) -> list[FigureCandidate]:
    try:
        pages = json.loads((parsed / "structured_content.json").read_text(encoding="utf-8"))["pages"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    found: list[FigureCandidate] = []
    for page in pages if isinstance(pages, list) else []:
        blocks = page.get("blocks") if isinstance(page, dict) else None
        run: list[Path] = []  # image files of the uncaptioned image/chart blocks just before
        for b in blocks if isinstance(blocks, list) else []:
            if not isinstance(b, dict) or b.get("type") not in ("image", "chart"):
                run = []
                continue
            path = inside(parsed, b.get("image_source"))
            caption = _caption(b)
            if caption is None:
                run += [path] if path else []
                continue
            panels = [*run, *([path] if path else [])][-MAX_PANELS:]
            run = []
            if panels:
                found.append(FigureCandidate(f"fig{len(found) + 1}", caption, panels, _mentions(markdown, caption)))
    return found


def pick(ids: list[str], candidates: list[FigureCandidate]) -> list[str]:
    """The model's choice, kept to known ids, no repeats, at most MAX_PICK."""
    known = {c.id for c in candidates}
    return list(dict.fromkeys(i for i in ids if i in known))[:MAX_PICK]


def load(parsed: Path) -> list[FigureCandidate]:
    try:
        return ParseResult.load(parsed).figures
    except (OSError, ValueError, KeyError, TypeError):  # no parse result (yet), or a damaged one
        return []


def shown(arxiv_id: str, parsed: Path, report: dict) -> list[dict]:
    """What the report screen draws: the picked candidates with caption and image urls, resolved from the candidates."""
    ids = report.get("figures")  # a report stored before #9 has none
    by_id = {c.id: c for c in load(parsed)}
    return [
        {"id": i, "caption": html.unescape(by_id[i].caption), "images": [f"/api/papers/{arxiv_id}/figures/{i}/{n}" for n in range(len(by_id[i].images))]}
        for i in (ids if isinstance(ids, list) else [])
        if i in by_id
    ]
