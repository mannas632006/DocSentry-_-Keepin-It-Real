"""CLI argument wiring and output encoding."""
from __future__ import annotations

import pytest

from docsentry.cli import build_parser, main


def _parse(argv):
    return build_parser().parse_args(argv)


def test_dry_run_tristate():
    """None = inherit the environment, True = force on, False = force off.
    `--dry-run` alone could only ever turn it on, so a deployment with
    dry_run=true (as render.yaml ships) had no way to act."""
    assert _parse(["run"]).dry_run is None
    assert _parse(["run", "--dry-run"]).dry_run is True
    assert _parse(["run", "--no-dry-run"]).dry_run is False


def test_dry_run_flags_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        _parse(["run", "--dry-run", "--no-dry-run"])


def test_run_accepts_threshold_overrides():
    args = _parse(["run", "abc123", "--autofix-threshold", "0.9",
                   "--alert-threshold", "0.2", "--max-docs", "3"])
    assert args.commit == "abc123"
    assert args.autofix_threshold == 0.9
    assert args.alert_threshold == 0.2
    assert args.max_docs == 3


def test_commit_is_optional():
    assert _parse(["run"]).commit is None


def test_every_command_is_wired():
    for cmd in ("doctor", "index", "run", "config", "serve", "dashboard"):
        assert callable(_parse([cmd]).func)


def test_run_accepts_history_flag():
    assert _parse(["run", "--history", "h.json"]).history == "h.json"
    assert _parse(["run"]).history is None


def test_dashboard_command_writes_a_file(tmp_path, capsys):
    assert main(["dashboard", "--out", str(tmp_path),
                 "--history-url", "https://x/history.json"]) == 0
    out = tmp_path / "dashboard.html"
    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    assert "https://x/history.json" in html
    assert html.strip().startswith("<!doctype html>")


def test_a_command_is_required():
    with pytest.raises(SystemExit):
        _parse([])


def test_config_command_prints_no_secrets(capsys, isolated_settings):
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert "llm_provider" in out
    assert "test-token" not in out    # github_token from the fixture
    assert "test-key" not in out      # llm_api_key from the fixture


def test_run_reports_missing_config_instead_of_raising(capsys, monkeypatch,
                                                       isolated_settings):
    monkeypatch.setattr(isolated_settings, "github_token", "")
    assert main(["run"]) == 1
    err = capsys.readouterr().err
    assert "Not ready to run" in err
    assert "github_token" in err


def test_stdout_is_forced_to_utf8():
    """Printing a finding containing '→' raised UnicodeEncodeError on a Windows
    cp1252 console and took the whole command down."""
    import sys
    from docsentry.cli import _force_utf8_stdout

    _force_utf8_stdout()
    # Must not raise, whatever the console's native encoding is.
    sys.stdout.write("`divide` default changed: `True` → `False`\n")
