import subprocess

import pytest

import policy_fetcher.llm_spider as llm_spider


LINKS = [
    ("Terms of Service", "https://example.org/terms"),
    ("Privacy Policy", "https://other.example/privacy"),
    ("Donate", "https://example.org/donate"),
]


def test_rank_policy_links_no_links_returns_empty():
    assert llm_spider.rank_policy_links("about text", []) == []


def test_rank_policy_links_llm_missing(monkeypatch):
    monkeypatch.setattr(llm_spider.shutil, "which", lambda name: None)
    assert llm_spider.rank_policy_links("about text", LINKS) == []


def test_rank_policy_links_happy_path(monkeypatch):
    monkeypatch.setattr(llm_spider.shutil, "which", lambda name: "/usr/bin/llm")

    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout="https://example.org/terms\n", stderr=""
        )

    monkeypatch.setattr(llm_spider.subprocess, "run", fake_run)

    result = llm_spider.rank_policy_links("about text", LINKS)
    assert result == ["https://example.org/terms"]
    assert "-m" in captured["cmd"]


def test_rank_policy_links_ignores_invented_urls(monkeypatch):
    monkeypatch.setattr(llm_spider.shutil, "which", lambda name: "/usr/bin/llm")

    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            cmd,
            returncode=0,
            stdout="https://evil.example/phish\nhttps://example.org/donate\n",
            stderr="",
        )

    monkeypatch.setattr(llm_spider.subprocess, "run", fake_run)

    result = llm_spider.rank_policy_links("about text", LINKS)
    # evil.example was never a candidate -- must be dropped.
    assert result == ["https://example.org/donate"]


def test_rank_policy_links_none_response(monkeypatch):
    monkeypatch.setattr(llm_spider.shutil, "which", lambda name: "/usr/bin/llm")

    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="NONE\n", stderr="")

    monkeypatch.setattr(llm_spider.subprocess, "run", fake_run)

    assert llm_spider.rank_policy_links("about text", LINKS) == []


def test_rank_policy_links_nonzero_exit(monkeypatch):
    monkeypatch.setattr(llm_spider.shutil, "which", lambda name: "/usr/bin/llm")

    def fake_run(cmd, capture_output, text, timeout):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(llm_spider.subprocess, "run", fake_run)

    assert llm_spider.rank_policy_links("about text", LINKS) == []


def test_rank_policy_links_subprocess_error(monkeypatch):
    monkeypatch.setattr(llm_spider.shutil, "which", lambda name: "/usr/bin/llm")

    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(llm_spider.subprocess, "run", fake_run)

    assert llm_spider.rank_policy_links("about text", LINKS) == []


def test_select_model_explicit_override():
    assert llm_spider.select_model("custom-model") == "custom-model"


def test_select_model_fallback_no_env(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert llm_spider.select_model() == llm_spider.FALLBACK_MODEL


def test_select_model_openrouter_when_configured(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    assert llm_spider.select_model() == "openrouter/anthropic/claude-3.5-sonnet"


def test_select_model_openrouter_without_key_falls_back(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert llm_spider.select_model() == llm_spider.FALLBACK_MODEL
