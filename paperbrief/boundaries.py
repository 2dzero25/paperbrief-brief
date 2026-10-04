"""The four external boundaries, injected into `create_app`. Tests pass fakes; PAPERBRIEF_OFFLINE=1 passes `offline()`."""
from dataclasses import dataclass

from paperbrief import arxiv, hf, llm, parser
from paperbrief.arxiv import ArxivClient
from paperbrief.config import Settings
from paperbrief.hf import HFClient
from paperbrief.llm import LLMClient
from paperbrief.parser import Parser


@dataclass(frozen=True)
class Boundaries:
    hf: HFClient
    arxiv: ArxivClient
    llm: LLMClient
    parser: Parser


def live(settings: Settings) -> Boundaries:
    return Boundaries(hf.live(settings), arxiv.live(settings), llm.live(settings), parser.live(settings))


def offline(settings: Settings) -> Boundaries:
    return Boundaries(hf.offline(settings), arxiv.offline(settings), llm.offline(settings), parser.offline(settings))
