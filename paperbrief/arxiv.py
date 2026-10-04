"""Boundary 2/4: arXiv API (categories only). The collection ticket implements `live()` and `offline()`."""
from typing import Protocol

from paperbrief.config import Settings


class ArxivClient(Protocol):
    def categories(self, arxiv_ids: list[str]) -> dict[str, tuple[str, list[str]]]:
        """arxiv_id -> (primary category, all categories). Owns the 3 s rate limit and User-Agent."""
        ...


class _Unimplemented:
    def categories(self, arxiv_ids: list[str]) -> dict[str, tuple[str, list[str]]]:
        raise NotImplementedError("arXiv client not implemented yet")


def live(settings: Settings) -> ArxivClient:
    return _Unimplemented()


def offline(settings: Settings) -> ArxivClient:
    """Serves recorded fixtures from tests/fixtures."""
    return _Unimplemented()
