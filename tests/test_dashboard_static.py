"""The self-contained static dashboard."""
from __future__ import annotations

from docsentry.dashboard_static import render_dashboard


def test_injects_the_history_url():
    html = render_dashboard("https://example.com/data/history.json")
    assert 'HISTORY_URL = "https://example.com/data/history.json"' in html
    # The placeholder must be fully substituted.
    assert "__HISTORY_URL__" not in html


def test_defaults_to_relative_history_json():
    assert 'HISTORY_URL = "history.json"' in render_dashboard()


def test_is_self_contained():
    """No external CSS/JS/font/image — it must work on a static host and off
    disk. The only outbound request is the history fetch, at runtime."""
    html = render_dashboard()
    for needle in ("<script src", 'link rel="stylesheet"', "http-equiv",
                   "cdn.", "googleapis", "unpkg", "jsdelivr"):
        assert needle not in html, f"unexpected external reference: {needle}"
    assert "<style>" in html and "</script>" in html


def test_renders_the_status_vocabulary():
    """Every status the pipeline can emit needs a label and a badge class, or
    it shows up unstyled."""
    html = render_dashboard()
    for status in ("auto_fixed", "alerted", "fix_failed_verification", "clean",
                   "low_confidence_skip", "no_semantic_changes", "error"):
        assert status in html


def test_is_theme_aware():
    html = render_dashboard()
    assert "prefers-color-scheme" in html
    assert 'data-theme' in html


def test_valid_html_document():
    html = render_dashboard()
    assert html.strip().startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
