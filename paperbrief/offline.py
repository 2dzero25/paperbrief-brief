"""Shared bits of the `PAPERBRIEF_OFFLINE=1` fakes."""
import os


def delay() -> float:
    """Seconds each fake stage pretends to work, so the progress can be watched in a demo. Default 0."""
    return float(os.environ.get("PAPERBRIEF_OFFLINE_DELAY") or 0)
