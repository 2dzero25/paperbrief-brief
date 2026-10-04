"""Boundary 4/4: PDF parser (MinerU runner). `live()` is #13; `offline()` serves a canned body."""
import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from paperbrief.config import Settings
from paperbrief.hf import FIXTURES_DIR
from paperbrief.offline import delay

RESULT_FILE = "parse_result.json"  # written by the worker after `parse` returns; its presence means 파싱 is done


@dataclass(frozen=True)
class FigureCandidate:
    """A 그림 후보 (built by `figures.extract`): caption starts with `Figure`, image files exist, panels merged."""

    id: str
    caption: str
    images: list[Path]  # the panels in order; one file for a single-image figure
    mentions: list[str] = field(default_factory=list)  # sentences of the body that cite this figure


@dataclass(frozen=True)
class ParseResult:
    markdown: str
    figures: list[FigureCandidate] = field(default_factory=list)

    def save(self, out_dir: Path) -> None:
        data = {"markdown": self.markdown, "figures": [{**asdict(f), "images": [str(i) for i in f.images]} for f in self.figures]}
        (out_dir / RESULT_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, out_dir: Path) -> "ParseResult":
        data = json.loads((out_dir / RESULT_FILE).read_text(encoding="utf-8"))
        return cls(data["markdown"], [FigureCandidate(**{**f, "images": [Path(i) for i in f["images"]]}) for f in data["figures"]])


class Parser(Protocol):
    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        """Owns the subprocess call, tier fallback (standard -> basic) and zip extraction."""
        ...


class _Unimplemented:
    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        raise NotImplementedError("parser not implemented yet")


def live(settings: Settings) -> Parser:
    return _Unimplemented()


class OfflineParser:
    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        time.sleep(delay())
        shutil.copytree(FIXTURES_DIR / "mineru_offline", out_dir, dirs_exist_ok=True)  # hand-made MinerU output (#9)
        return ParseResult(markdown=(FIXTURES_DIR / "parse_offline.md").read_text(encoding="utf-8"))


def offline(settings: Settings) -> Parser:
    """Returns a canned body and a hand-made MinerU output folder (`PAPERBRIEF_OFFLINE=1`)."""
    return OfflineParser()
