"""Offline tests for OpenRouter model-candidate ordering and rotation.

No network: the client is faked; only list-building and fallback logic run.
"""

from types import SimpleNamespace

import pytest

from activist.engine.openrouter import RotatingCompleter, _env_file_values, candidate_models

ENV_TEXT = """\
# comment line
OPENROUTER_API_KEY=sk-or-secret
OPENROUTER_MODELS_FREE=google/gemma-4-31b-it
OPENROUTER_MODELS_FREE=google/gemma-4-31b-it:free
OPENROUTER_ROTATE_MODELS=true
"""


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(ENV_TEXT, encoding="utf-8")
    return path


def test_env_file_repeated_keys_all_collected(env_file):
    assert _env_file_values("OPENROUTER_MODELS_FREE", env_file) == [
        "google/gemma-4-31b-it",
        "google/gemma-4-31b-it:free",
    ]
    assert _env_file_values("NO_SUCH_KEY", env_file) == []


def test_candidate_models_free_tier_first_then_paid(env_file, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
    assert candidate_models(env_file) == [
        "google/gemma-4-31b-it:free",
        "google/gemma-4-31b-it",
        "anthropic/claude-3.5-sonnet",
    ]


def test_candidate_models_dedupes(env_file, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemma-4-31b-it")
    assert candidate_models(env_file) == [
        "google/gemma-4-31b-it:free",
        "google/gemma-4-31b-it",
    ]


def _fake_client(behavior):
    """behavior: model -> reply string, or an Exception to raise."""

    def create(model, messages):
        result = behavior[model]
        if isinstance(result, Exception):
            raise result
        message = SimpleNamespace(content=result)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_rotation_skips_failing_model_and_sticks():
    client = _fake_client(
        {
            "free-model": RuntimeError("429 rate limited"),
            "paid-model": "ok from paid",
        }
    )
    completer = RotatingCompleter(["free-model", "paid-model"], client)
    assert completer.complete("s", "u") == "ok from paid"
    assert completer.active_model == "paid-model"
    # next call goes straight to the surviving model
    assert completer.complete("s", "u") == "ok from paid"


def test_empty_completion_counts_as_failure():
    client = _fake_client({"free-model": "   ", "paid-model": "real reply"})
    completer = RotatingCompleter(["free-model", "paid-model"], client)
    assert completer.complete("s", "u") == "real reply"
    assert completer.active_model == "paid-model"


def test_first_model_working_is_kept():
    client = _fake_client({"free-model": "free reply", "paid-model": "paid reply"})
    completer = RotatingCompleter(["free-model", "paid-model"], client)
    assert completer.complete("s", "u") == "free reply"
    assert completer.active_model == "free-model"


def test_all_models_failing_raises_with_context():
    client = _fake_client(
        {"free-model": RuntimeError("404"), "paid-model": RuntimeError("401")}
    )
    completer = RotatingCompleter(["free-model", "paid-model"], client)
    with pytest.raises(RuntimeError, match="All OpenRouter candidates failed"):
        completer.complete("s", "u")


def test_no_models_rejected():
    with pytest.raises(ValueError):
        RotatingCompleter([], _fake_client({}))
