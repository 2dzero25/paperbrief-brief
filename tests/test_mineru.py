"""Seam: HTTP API through TestClient. Ticket #13: the real parser's `mineru-kit` call, with the subprocess faked.

The fake stands in for `mineru-kit parse <pdf> -o <dir> -f zip --tier <t>`: it writes `<dir>/<pdf stem>.zip` laid out like
the real tool does (checked on real papers; see tests/fixtures/mineru/README.txt), or fails the way the tool fails.
"""
import io
import json
import subprocess
import zipfile
from functools import partial
import re
from pathlib import Path

import pytest

from paperbrief.mineru import run_mineru
from paperbrief.parser import TieredParser
from tests.test_reports import start, wait_status

FIXTURES = Path(__file__).parent / "fixtures" / "mineru"

MARKDOWN = "# Title\n\n![](images/page_0_image_1.jpg)\n\nFigure 1. A caption.\n"
STRUCTURED = {"pages": [{"page_idx": 0, "blocks": [{"type": "image", "image_source": "images/page_0_image_1.jpg"}]}]}


def mineru_zip(markdown: str = MARKDOWN) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("markdown.md", markdown)
        z.writestr("structured_content.json", json.dumps(STRUCTURED))
        z.writestr("middle_json.json", "{}")  # the tool also writes these; we do not keep them
        z.writestr("model_output.json", "[]")
        z.writestr("images/page_0_image_1.jpg", b"jpg")
    return buf.getvalue()


class FakeMineru:
    """Replaces `subprocess.run`. `script` has one entry per call: a zip (bytes), or an int exit code (stderr says why)."""

    def __init__(self, *script: bytes | int) -> None:
        self.script = list(script)
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.commands.append(cmd)
        step = self.script.pop(0)
        if isinstance(step, int):
            return subprocess.CompletedProcess(cmd, step, "", "CUDA out of memory")
        out = Path(cmd[cmd.index("-o") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{Path(cmd[2]).stem}.zip").write_bytes(step)
        return subprocess.CompletedProcess(cmd, 0, "", "Parsed 1 input(s).")


def parser_with(fake: FakeMineru) -> TieredParser:
    return TieredParser(partial(run_mineru, run=fake))


def test_the_report_is_written_from_the_markdown_in_mineru_zip_and_its_files_are_kept(make_client):
    fake = FakeMineru(mineru_zip())
    client, _, llm, _ = start(make_client, parser=parser_with(fake))
    client.post("/api/papers/2610.00001/report")
    wait_status(client, "2610.00001", "완료")

    (cmd,) = fake.commands
    assert cmd[1:3] == ["parse", str(client.app.state.settings.data_dir / "papers" / "2610.00001" / "paper.pdf")]  # type: ignore[attr-defined]
    assert cmd[3:] == ["-o", cmd[4], "-f", "zip", "--tier", "standard"] and "mineru-kit" in cmd[0]
    assert [c[0] for c in llm.calls] == ["write_report"] and llm.calls[0][1][0] == MARKDOWN
    parsed = client.app.state.settings.data_dir / "papers" / "2610.00001" / "parsed"  # type: ignore[attr-defined]
    assert (parsed / "markdown.md").read_text(encoding="utf-8") == MARKDOWN
    assert json.loads((parsed / "structured_content.json").read_text(encoding="utf-8")) == STRUCTURED
    assert (parsed / "images" / "page_0_image_1.jpg").read_bytes() == b"jpg"
    assert not (parsed / "model_output.json").exists() and not list(parsed.glob("*.zip"))


def test_when_the_gpu_tier_fails_the_cpu_tier_is_tried_and_the_report_still_gets_made(make_client):
    fake = FakeMineru(1, mineru_zip())
    client, _, llm, _ = start(make_client, parser=parser_with(fake))
    client.post("/api/papers/2610.00001/report")
    wait_status(client, "2610.00001", "완료")

    assert [c[c.index("--tier") + 1] for c in fake.commands] == ["standard", "basic"]
    assert llm.calls[0][1][0] == MARKDOWN


def test_a_failed_parse_logs_why_for_every_tier_tried(make_client):
    fake = FakeMineru(1, 3)
    client, _, llm, _ = start(make_client, parser=parser_with(fake))
    client.post("/api/papers/2610.00001/report")
    failed = wait_status(client, "2610.00001", "실패")

    assert failed["stage"] == "파싱"
    assert "[standard]" in failed["error_log"] and "[basic]" in failed["error_log"]
    assert "exited 1" in failed["error_log"] and "exited 3" in failed["error_log"] and "CUDA out of memory" in failed["error_log"]
    assert llm.calls == []


def test_a_zip_that_is_not_a_mineru_result_is_a_parse_failure(make_client):
    no_markdown = io.BytesIO()
    with zipfile.ZipFile(no_markdown, "w") as z:
        z.writestr("middle_json.json", "{}")
    fake = FakeMineru(b"not a zip", no_markdown.getvalue())
    client, _, _, _ = start(make_client, parser=parser_with(fake))
    client.post("/api/papers/2610.00001/report")
    failed = wait_status(client, "2610.00001", "실패")

    assert "broken zip" in failed["error_log"] and "no markdown.md" in failed["error_log"]
    parsed = client.app.state.settings.data_dir / "papers" / "2610.00001" / "parsed"  # type: ignore[attr-defined]
    assert not (parsed / "parse_result.json").exists()  # 파싱 stays undone, so 다시 시도 runs it again


def zip_of(folder: Path) -> bytes:
    """What `mineru-kit -f zip` writes for a recorded real output (plus the two files we do not keep)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in folder.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(folder).as_posix())
        z.writestr("middle_json.json", "{}")
        z.writestr("model_output.json", "[]")
    return buf.getvalue()


@pytest.mark.parametrize("paper", ["looped", "ego2act"])
def test_real_mineru_output_has_the_shapes_the_figure_code_relies_on(make_client, paper):
    """Recorded from real MinerU runs (tests/fixtures/mineru/README.txt); these are the facts of brief.md, checked."""
    fake = FakeMineru(zip_of(FIXTURES / paper))
    client, _, _, _ = start(make_client, parser=parser_with(fake))
    client.post("/api/papers/2610.00001/report")
    wait_status(client, "2610.00001", "완료")
    parsed = client.app.state.settings.data_dir / "papers" / "2610.00001" / "parsed"  # type: ignore[attr-defined]

    pages = json.loads((parsed / "structured_content.json").read_text(encoding="utf-8"))["pages"]
    blocks = [b for p in pages for b in p["blocks"]]
    assert "Figure" not in {b["type"] for b in blocks}  # there is no Figure block type
    # every image file is named page_{n}_{image|chart|table|equation}_{k}.jpg, matches its block type, and exists
    for b in blocks:
        if "image_source" in b:
            m = re.fullmatch(r"images/page_(\d+)_(image|chart|table|equation)_(\d+)\.jpg", b["image_source"])
            assert m and m.group(2) == b["type"] and (parsed / b["image_source"]).is_file()
    assert {b["type"] for b in blocks if "image_source" in b} >= {"chart", "table"}  # tables carry image_source too

    def figure_caption(b: dict) -> bool:
        return any(c["content"].startswith("Figure") for c in b["captions"])

    graphics = [b for b in blocks if b["type"] in ("image", "chart")]
    # "Figure" is not always the first caption: panel labels ("b", "(c) Recording duration") can stand in front of it
    assert [b for b in graphics if figure_caption(b) and not b["captions"][0]["content"].startswith("Figure")]
    # ...and some captions never start with "Figure" at all, so those blocks are no 그림 후보
    assert [b for b in graphics if b["captions"] and not figure_caption(b)]
    # multi-panel figure: the caption sits on the last panel, the panels in front of it have none
    per_page = [[b for b in p["blocks"] if b["type"] in ("image", "chart")] for p in pages]
    assert any(not a["captions"] and figure_caption(b) for g in per_page for a, b in zip(g, g[1:]))
