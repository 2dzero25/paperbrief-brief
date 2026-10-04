"""Boundary 4/4: PDF parser (MinerU runner). `live()` is #13; `offline()` serves a canned body."""
import json
import logging
import shutil
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from paperbrief.config import Settings
from paperbrief.hf import FIXTURES_DIR
from paperbrief.offline import delay, fail_once

log = logging.getLogger(__name__)

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
        """Image paths are stored relative to `out_dir` (posix style), so moving the data dir keeps them valid."""
        root = out_dir.resolve()
        data = {"markdown": self.markdown, "figures": [{**asdict(f), "images": [_relative(i, root) for i in f.images]} for f in self.figures]}
        (out_dir / RESULT_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, out_dir: Path) -> "ParseResult":
        """Files saved by older versions hold absolute image paths; those are kept as they are."""
        data = json.loads((out_dir / RESULT_FILE).read_text(encoding="utf-8"))
        return cls(data["markdown"], [FigureCandidate(**{**f, "images": [(out_dir / i).resolve() for i in f["images"]]}) for f in data["figures"]])  # an absolute `i` wins over `out_dir`


def _relative(image: Path, root: Path) -> str:
    try:
        return image.resolve().relative_to(root).as_posix()
    except ValueError:  # not under the parsed folder: keep it as given
        return str(image)


class Parser(Protocol):
    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        """Owns the subprocess call, tier fallback (standard -> basic) and zip extraction."""
        ...


class TieredParser:
    """MinerU tier fallback. `runner(pdf, out_dir, tier)` (`mineru.run_mineru`, #13) parses once with one tier and raises
    on failure; this tries `standard`, then `basic`. When every tier fails it raises one error holding all their logs."""

    def __init__(self, runner: Callable[[Path, Path, str], ParseResult], tiers: tuple[str, ...] = ("standard", "basic")) -> None:
        self._runner = runner
        self._tiers = tiers

    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        logs: list[str] = []
        for tier in self._tiers:
            try:
                return self._runner(pdf, out_dir, tier)
            except Exception:
                logs.append(f"[{tier}] 실패\n{traceback.format_exc()}")
                log.warning("MinerU %s tier failed for %s", tier, pdf, exc_info=True)
        raise RuntimeError(f"파싱 실패: {' + '.join(self._tiers)} tier 모두 실패\n\n" + "\n".join(logs))


def live(settings: Settings) -> Parser:
    from paperbrief.mineru import run_mineru  # imported here: mineru.py imports ParseResult from this module

    # PAPERBRIEF_MINERU_TIER=basic skips the GPU tier altogether
    return TieredParser(run_mineru, ("basic",) if settings.mineru_tier == "basic" else ("standard", "basic"))


class OfflineParser:
    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        time.sleep(delay())
        shutil.copytree(FIXTURES_DIR / "mineru_offline", out_dir, dirs_exist_ok=True)  # hand-made MinerU output (#9)
        fail_once("파싱")
        return ParseResult(markdown=(FIXTURES_DIR / "parse_offline.md").read_text(encoding="utf-8"))


def offline(settings: Settings) -> Parser:
    """Returns a canned body and a hand-made MinerU output folder (`PAPERBRIEF_OFFLINE=1`)."""
    return OfflineParser()
