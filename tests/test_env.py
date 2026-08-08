"""Tests for .env loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ledger_agent.env import load_dotenv


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEDGER_TEST_KEY", raising=False)
    monkeypatch.delenv("LEDGER_TEST_OTHER", raising=False)


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_a_simple_pair(tmp_path: Path) -> None:
    load_dotenv(write(tmp_path, "LEDGER_TEST_KEY=abc123\n"))
    assert os.environ["LEDGER_TEST_KEY"] == "abc123"


def test_existing_environment_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A deliberately exported value must never be silently overridden by a file."""
    monkeypatch.setenv("LEDGER_TEST_KEY", "from-shell")
    load_dotenv(write(tmp_path, "LEDGER_TEST_KEY=from-file\n"))
    assert os.environ["LEDGER_TEST_KEY"] == "from-shell"


def test_missing_file_is_not_an_error(tmp_path: Path) -> None:
    load_dotenv(tmp_path / "does-not-exist")


def test_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    body = "\n# a comment\n\n  \nLEDGER_TEST_KEY=value\n#LEDGER_TEST_OTHER=nope\n"
    load_dotenv(write(tmp_path, body))
    assert os.environ["LEDGER_TEST_KEY"] == "value"
    assert "LEDGER_TEST_OTHER" not in os.environ


def test_strips_surrounding_quotes(tmp_path: Path) -> None:
    load_dotenv(write(tmp_path, 'LEDGER_TEST_KEY="quoted"\nLEDGER_TEST_OTHER=\'single\'\n'))
    assert os.environ["LEDGER_TEST_KEY"] == "quoted"
    assert os.environ["LEDGER_TEST_OTHER"] == "single"


def test_keeps_equals_signs_inside_the_value(tmp_path: Path) -> None:
    """Base64 and similar values contain '=', so only the first one separates."""
    load_dotenv(write(tmp_path, "LEDGER_TEST_KEY=a=b=c\n"))
    assert os.environ["LEDGER_TEST_KEY"] == "a=b=c"


def test_ignores_lines_without_a_separator(tmp_path: Path) -> None:
    load_dotenv(write(tmp_path, "NOT_A_PAIR\nLEDGER_TEST_KEY=fine\n"))
    assert os.environ["LEDGER_TEST_KEY"] == "fine"


def test_the_shipped_example_parses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """.env.example must be copyable to .env and actually work.

    The real key is cleared first — otherwise this passes off a developer's exported
    value and proves nothing about the file.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    example = Path(__file__).resolve().parent.parent / ".env.example"
    assert example.is_file(), "the repo ships a .env.example"
    target = tmp_path / ".env"
    target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    load_dotenv(target)
    assert os.environ.get("ANTHROPIC_API_KEY"), ".env.example does not define the key it implies"
