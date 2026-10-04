"""Hand-made MinerU output (brief.md "MinerU 출력"): `markdown.md`, `structured_content.json`, `images/page_{n}_{kind}_{k}.jpg`.

Layout as seen in a real `mineru-kit parse -f zip` run: `{"pages": [{"page_idx": n, "blocks": [...]}]}`, a block is
`{"type", "bbox", "captions": [{"content"}], "image_source": "images/..."}`; no block has type "Figure". Images are
tiny generated placeholders, never real paper images. #13 later adds fixtures cut from a real run in the same format.
"""
import io
import json
from pathlib import Path

from PIL import Image

from paperbrief.parser import ParseResult
from tests.fakes import FakeParser


def jpeg(color: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(out, "JPEG")
    return out.getvalue()


def block(kind: str, captions: list[str], image: str | None = None) -> dict:
    b: dict = {"type": kind, "bbox": [0, 0, 100, 100], "captions": [{"content": c} for c in captions]}
    if image is not None:
        b["image_source"] = image
    return b


class MineruFixtureParser(FakeParser):
    """Writes a MinerU output folder into `out_dir` the way the real runner will, then returns the markdown only."""

    def __init__(self, markdown: str, pages: list[list[dict]], files: dict[str, bytes]) -> None:
        super().__init__(ParseResult(markdown=markdown))
        self.pages, self.files = pages, files

    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        (out_dir / "markdown.md").write_text(self.result.markdown, encoding="utf-8")
        content = {"pages": [{"page_idx": n, "blocks": blocks} for n, blocks in enumerate(self.pages)]}
        (out_dir / "structured_content.json").write_text(json.dumps(content), encoding="utf-8")
        for name, data in self.files.items():
            (out_dir / name).parent.mkdir(parents=True, exist_ok=True)
            (out_dir / name).write_bytes(data)
        return super().parse(pdf, out_dir)
