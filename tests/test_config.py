import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_ENV = {
    "GOOGLE_MAPS_BROWSER_KEY": "browser-key",
    "GOOGLE_MAPS_MAP_ID": "map-id",
    "LLM_API_KEY": "llm-key",
    "LLM_MODEL": "claude-sonnet-4-5",
}


def _base_env(monkeypatch):
    for key in (
        *REQUIRED_ENV,
        "DATABASE_PATH",
        "STORY_INDEX_PATH",
        "RATE_LIMIT_PER_HOUR",
        "DAILY_MESSAGE_CAP",
    ):
        monkeypatch.delenv(key, raising=False)
    import os

    return dict(os.environ)


def _run(env, code, cwd):
    # cwd must NOT be REPO_ROOT: python-dotenv's find_dotenv(), invoked bare by
    # app.config, searches from the current working directory for `python -c`
    # invocations. Running from REPO_ROOT would silently pull in the real .env
    # (if present) and mask the env vars this test explicitly unset.
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env={**env, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
    )


def test_import_succeeds_with_all_required_variables_set(monkeypatch, tmp_path):
    env = {**_base_env(monkeypatch), **REQUIRED_ENV}

    result = _run(env, "from app.config import settings", tmp_path)

    assert result.returncode == 0, result.stderr


def test_defaults_apply_when_optional_variables_absent(monkeypatch, tmp_path):
    env = {**_base_env(monkeypatch), **REQUIRED_ENV}

    result = _run(
        env,
        "from app.config import settings\n"
        "print(settings.database_path, settings.story_index_path, "
        "settings.rate_limit_per_hour, settings.daily_message_cap)",
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "travel.db stories.faiss 10 300"


def test_optional_variables_are_overridable(monkeypatch, tmp_path):
    env = {
        **_base_env(monkeypatch),
        **REQUIRED_ENV,
        "DATABASE_PATH": "/tmp/other.db",
        "STORY_INDEX_PATH": "/tmp/other.faiss",
        "RATE_LIMIT_PER_HOUR": "25",
        "DAILY_MESSAGE_CAP": "1000",
    }

    result = _run(
        env,
        "from app.config import settings\n"
        "print(settings.database_path, settings.story_index_path, "
        "settings.rate_limit_per_hour, settings.daily_message_cap)",
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/tmp/other.db /tmp/other.faiss 25 1000"


@pytest.mark.parametrize("missing", list(REQUIRED_ENV))
def test_missing_required_variable_raises_naming_it(monkeypatch, tmp_path, missing):
    env = {**_base_env(monkeypatch), **REQUIRED_ENV}
    del env[missing]

    result = _run(env, "from app.config import settings", tmp_path)

    assert result.returncode != 0
    assert missing in result.stderr


def test_settings_object_has_no_places_api_key_field(monkeypatch, tmp_path):
    env = {**_base_env(monkeypatch), **REQUIRED_ENV}

    result = _run(
        env,
        "from app.config import settings; print(hasattr(settings, 'google_places_api_key'))",
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
