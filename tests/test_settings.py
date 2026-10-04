"""Seam: settings loading (environment + `.env`) and the server config built from it."""
from pathlib import Path

from paperbrief.config import Settings
from paperbrief.server import make_config
from paperbrief.app import create_app
from tests.fakes import fake_boundaries


def test_defaults_need_no_env_and_no_key(tmp_path: Path):
    s = Settings.load({}, env_file=None)
    assert s.port == 8765
    assert s.openai_api_key == ""
    assert s.offline is False


def test_dotenv_is_read_and_real_env_wins(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nPAPERBRIEF_PORT=9000\nOPENAI_API_KEY='from-file'\nOPENAI_MODEL=m-file\n", encoding="utf-8")
    s = Settings.load({"OPENAI_MODEL": "m-env"}, env_file=env_file)
    assert (s.port, s.openai_api_key, s.openai_model) == (9000, "from-file", "m-env")


def test_blank_values_from_env_example_fall_back_to_defaults():
    s = Settings.load({"PAPERBRIEF_PORT": "", "OPENAI_MODEL": ""}, env_file=None)
    assert s.port == 8765 and s.openai_model == "gpt-6.1-sol"


def test_server_listens_on_loopback_only_on_configured_port(tmp_path: Path):
    settings = Settings(port=9123, data_dir=tmp_path)
    config = make_config(create_app(settings, fake_boundaries()), settings)
    assert (config.host, config.port) == ("127.0.0.1", 9123)


def test_data_dir_is_outside_the_repo_and_overridable(tmp_path: Path):
    repo = Path(__file__).resolve().parent.parent
    assert repo not in Settings.load({}, env_file=None).data_dir.parents
    assert Settings.load({"PAPERBRIEF_DATA_DIR": str(tmp_path)}, env_file=None).data_dir == tmp_path
