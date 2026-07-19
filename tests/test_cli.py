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


def test_apply_and_dismiss_require_an_issue_number():
    assert _parse(["apply", "--issue", "7"]).issue == 7
    assert _parse(["dismiss", "--issue", "7"]).issue == 7
    with pytest.raises(SystemExit):
        _parse(["apply"])


def test_apply_opens_a_pr_from_the_reviewed_fix(monkeypatch, isolated_settings):
    """`docsentry apply --issue N` reads the fix embedded in the issue and opens
    a PR with it — no LLM call, exactly the reviewed change."""
    from docsentry.agents.review import encode_fix
    from docsentry.cli import main

    verdict = {"doc_id": "README.md::38", "doc_file": "README.md",
               "doc_heading": "round_to", "doc_start_line": 38, "doc_end_line": 47,
               "confidence": 0.9, "mismatch": "wrong",
               "suggested_fix": "## round_to\n\nDefaults to 10."}
    change = {"file": "calculator.py", "kind": "default_changed",
              "name": "round_to", "detail": "changed 2 -> 10"}
    body = "Review issue.\n" + encode_fix(verdict, change, "sha1")

    calls = {}

    def fake_pr(v, c, **k):
        calls["pr"] = (v, c)
        return "https://gh/pull/9"

    def fake_comment(n, b):
        calls["comment"] = (n, b)

    def fake_close(n, **k):
        calls["closed"] = n

    # cmd_apply uses function-local imports, so patching the module attributes
    # (resolved at call time) is enough.
    monkeypatch.setattr("docsentry.core.github_ops.get_issue_body", lambda n: body)
    monkeypatch.setattr("docsentry.core.git_ops.ensure_repo", lambda **k: ".")
    monkeypatch.setattr("docsentry.agents.auto_fixer.open_fix_pr", fake_pr)
    monkeypatch.setattr("docsentry.core.github_ops.comment_on_issue", fake_comment)
    monkeypatch.setattr("docsentry.core.github_ops.close_issue", fake_close)

    assert main(["apply", "--issue", "9"]) == 0
    assert calls["pr"][0]["suggested_fix"] == "## round_to\n\nDefaults to 10."
    assert "pull/9" in calls["comment"][1]
    assert calls["closed"] == 9


def test_apply_on_a_non_docsentry_issue_is_a_no_op(monkeypatch, isolated_settings):
    from docsentry.cli import main
    monkeypatch.setattr("docsentry.core.github_ops.get_issue_body",
                        lambda n: "a normal issue, no fix payload")
    commented = {}
    monkeypatch.setattr("docsentry.core.github_ops.comment_on_issue",
                        lambda n, b: commented.setdefault(n, b))
    assert main(["apply", "--issue", "5"]) == 1
    assert "nothing to apply" in commented[5]


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
