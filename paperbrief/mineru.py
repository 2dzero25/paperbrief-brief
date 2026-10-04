"""The real parser: one `mineru-kit parse` subprocess per tier, its zip unpacked into the paper's `parsed/` folder.

`mineru parse` is not used (it needs a server and parses only the first 10 pages). `-f zip` is what puts the figures in
`images/` as files. After a run `out_dir` holds `markdown.md`, `structured_content.json` and `images/` (the tool's
`middle_json.json` and the huge `model_output.json` are not kept). The tier fallback lives in `parser.TieredParser`.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from paperbrief.parser import ParseResult

KEEP = ("markdown.md", "structured_content.json")  # plus everything under images/
TIMEOUT = 60 * 60  # seconds; a 78-page paper takes about 3 minutes on the GPU, this only frees a hung tool


def mineru_kit() -> str:
    """The `mineru-kit` of the venv we run in, even when the venv is not on PATH."""
    search = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
    return shutil.which("mineru-kit", path=search) or "mineru-kit"


def run_mineru(pdf: Path, out_dir: Path, tier: str, *, run=subprocess.run) -> ParseResult:
    """Parse `pdf` at `tier` ("standard" = GPU, "basic" = CPU) into `out_dir`. Raises RuntimeError with the reason."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out_dir, prefix="zip-") as tmp:
        cmd = [mineru_kit(), "parse", str(pdf), "-o", tmp, "-f", "zip", "--tier", tier]
        try:
            done = run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"mineru-kit --tier {tier}: no result after {TIMEOUT}s") from e
        if done.returncode != 0:
            raise RuntimeError(f"mineru-kit --tier {tier} exited {done.returncode}: {(done.stderr or '').strip()[-2000:]}")
        zips = list(Path(tmp).glob("*.zip"))
        if len(zips) != 1:
            raise RuntimeError(f"mineru-kit --tier {tier} wrote no zip (found {len(zips)}): {(done.stderr or '').strip()[-2000:]}")
        try:
            _unpack(zips[0], out_dir)
        except zipfile.BadZipFile as e:
            raise RuntimeError(f"mineru-kit --tier {tier} wrote a broken zip: {e}") from e
    return ParseResult(markdown=(out_dir / "markdown.md").read_text(encoding="utf-8"))


def _unpack(zip_path: Path, out_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n in KEEP or (n.startswith("images/") and not n.endswith("/"))]
        if "markdown.md" not in names:
            raise RuntimeError("mineru zip has no markdown.md")
        root = out_dir.resolve()
        targets = {name: (out_dir / Path(*name.replace("\\", "/").split("/"))).resolve() for name in names}
        for name, target in targets.items():  # check every entry first, so a rejected zip writes nothing
            if not target.is_relative_to(root):
                raise RuntimeError(f"mineru zip has an unsafe path: {name!r}")
        for name, target in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
