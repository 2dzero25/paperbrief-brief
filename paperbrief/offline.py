"""Shared bits of the `PAPERBRIEF_OFFLINE=1` fakes."""
import os


_failed: set[str] = set()


def fail_once(stage: str) -> None:
    """`PAPERBRIEF_OFFLINE_FAIL=파싱` (or `작성`) makes that fake stage fail its first run, to see 실패 and [다시 시도]."""
    if os.environ.get("PAPERBRIEF_OFFLINE_FAIL") == stage and stage not in _failed:
        _failed.add(stage)
        raise RuntimeError(f"offline: {stage} forced to fail by PAPERBRIEF_OFFLINE_FAIL")


def delay() -> float:
    """Seconds each fake stage pretends to work, so the progress can be watched in a demo. Default 0."""
    return float(os.environ.get("PAPERBRIEF_OFFLINE_DELAY") or 0)
