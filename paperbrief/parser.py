"""Boundary 4/4: PDF parser (MinerU runner). `live()` is #13; `offline()` serves a canned body."""
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from paperbrief.config import Settings
from paperbrief.hf import FIXTURES_DIR
from paperbrief.offline import delay

RESULT_FILE = "parse_result.json"  # written by the worker after `parse` returns; its presence means 파싱 is done


@dataclass(frozen=True)
class FigureCandidate:
    """A 그림 후보: caption starts with `Figure`, image file exists. Panels are already merged."""

    id: str
    caption: str
    image: Path
    mentions: list[str] = field(default_factory=list)  # sentences of the body that cite this figure


@dataclass(frozen=True)
class ParseResult:
    markdown: str
    figures: list[FigureCandidate] = field(default_factory=list)

    def save(self, out_dir: Path) -> None:
        data = {"markdown": self.markdown, "figures": [{**asdict(f), "image": str(f.image)} for f in self.figures]}
        (out_dir / RESULT_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, out_dir: Path) -> "ParseResult":
        data = json.loads((out_dir / RESULT_FILE).read_text(encoding="utf-8"))
        return cls(data["markdown"], [FigureCandidate(**{**f, "image": Path(f["image"])}) for f in data["figures"]])


class Parser(Protocol):
    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        """Owns the subprocess call, tier fallback (standard -> basic) and zip extraction."""
        ...


class TieredParser:
    """TEMPORARY (#13): minimal standard -> basic fallback so `live()` works before #8's `TieredParser(runner)` lands.

    #8 owns the real one (same name and constructor, logs both failures); drop this class when merging it.
    """

    def __init__(self, runner: Callable[[Path, Path, str], ParseResult], tiers: tuple[str, ...] = ("standard", "basic")) -> None:
        self.runner, self.tiers = runner, tiers

    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        errors: list[str] = []
        for tier in self.tiers:
            try:
                return self.runner(pdf, out_dir, tier)
            except Exception as e:
                errors.append(f"[{tier}] {e}")
        raise RuntimeError("\n".join(errors))


def live(settings: Settings) -> Parser:
    from paperbrief.mineru import run_mineru  # imported here: mineru.py imports ParseResult from this module

    # PAPERBRIEF_MINERU_TIER=basic skips the GPU tier altogether
    return TieredParser(run_mineru, ("basic",) if settings.mineru_tier == "basic" else ("standard", "basic"))


class OfflineParser:
    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        time.sleep(delay())
        return ParseResult(markdown=(FIXTURES_DIR / "parse_offline.md").read_text(encoding="utf-8"))


def offline(settings: Settings) -> Parser:
    """Returns a canned body (`PAPERBRIEF_OFFLINE=1`); no figures until #9 records a MinerU output folder."""
    return OfflineParser()
