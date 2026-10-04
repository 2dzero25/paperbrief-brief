"""Boundary 4/4: PDF parser (MinerU runner). The report ticket implements `live()` and `offline()`."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from paperbrief.config import Settings


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


class Parser(Protocol):
    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        """Owns the subprocess call, tier fallback (standard -> basic) and zip extraction."""
        ...


class _Unimplemented:
    def parse(self, pdf: Path, out_dir: Path) -> ParseResult:
        raise NotImplementedError("parser not implemented yet")


def live(settings: Settings) -> Parser:
    return _Unimplemented()


def offline(settings: Settings) -> Parser:
    """Returns a recorded MinerU output folder from tests/fixtures."""
    return _Unimplemented()
