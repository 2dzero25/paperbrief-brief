"""Settings from the process environment and `.env`. Nothing here needs the network or a key."""
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
HOST ="127.0.0.1"  # never configurable: the app must not be reachable from other machines


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "PaperBrief"
    return Path.home() / ".local" / "share" / "PaperBrief"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    port: int = 8765
    offline: bool = False
    openai_api_key: str = ""  # empty is fine: the app starts, only report writing needs it
    openai_model: str = "gpt-6.1-sol"
    openai_summary_model: str = "gpt-6-luna"
    arxiv_contact: str = ""
    mineru_tier: str = "standard"

    @classmethod
    def load(cls, environ: Mapping[str, str] | None = None, env_file: Path | None = ROOT / ".env") -> "Settings":
        """Real environment wins over `.env`. Pass `environ`/`env_file=None` in tests."""
        env = {**read_env_file(env_file), **(os.environ if environ is None else environ)}
        data_dir = env.get("PAPERBRIEF_DATA_DIR")
        return cls(
            data_dir=Path(data_dir) if data_dir else default_data_dir(),
            port=int(env.get("PAPERBRIEF_PORT") or 8765),
            offline=env.get("PAPERBRIEF_OFFLINE") == "1",
            openai_api_key=env.get("OPENAI_API_KEY", ""),
            openai_model=env.get("OPENAI_MODEL") or cls.openai_model,
            openai_summary_model=env.get("OPENAI_SUMMARY_MODEL") or cls.openai_summary_model,
            arxiv_contact=env.get("PAPERBRIEF_ARXIV_CONTACT", ""),
            mineru_tier=env.get("PAPERBRIEF_MINERU_TIER") or cls.mineru_tier,
        )


def read_env_file(path: Path | None) -> dict[str, str]:
    """Minimal KEY=VALUE parser: `#` comment lines, optional surrounding quotes."""
    if path is None or not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip("\"'")
    return out
