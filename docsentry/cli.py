"""Command line entry point: `docsentry <command>`."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from docsentry import __version__
from docsentry.config import settings

OK = "[ok]"
BAD = "[!!]"


def _log(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check that everything needed for a real run is present and reachable."""
    from docsentry.core.git_ops import GitOpsError, ensure_repo, redact
    from docsentry.llm import probe

    ok = True
    print(f"DocSentry {__version__}\n")

    print("Configuration")
    problems = settings.validate_for_run()
    if problems:
        ok = False
        for p in problems:
            print(f"  {BAD} {p}")
    else:
        print(f"  {OK} all required settings present")
    print(f"       provider={settings.llm_provider} model={settings.model}")
    print(f"       target_repo={settings.target_repo or '(unset)'}")
    print(f"       retrieval={settings.retrieval_backend} dry_run={settings.dry_run}")
    print(f"       data_dir={settings.data_dir}")

    print("\nLLM")
    info = probe()
    if info.get("reachable"):
        print(f"  {OK} {info['provider']} reachable at {info['base_url']}")
    else:
        ok = False
        print(f"  {BAD} {info['provider']} unreachable: {info.get('error', 'unknown')}")
        if settings.llm_provider == "ollama":
            print("       is `ollama serve` running?")

    print("\nWatched repository")
    try:
        path = ensure_repo(fetch=False)
        print(f"  {OK} {path}")
    except GitOpsError as e:
        ok = False
        print(f"  {BAD} {redact(e)}")

    print("\nDocumentation index")
    try:
        from docsentry.core import retrieval
        n = retrieval.reindex(str(ensure_repo(fetch=False)))
        if n:
            print(f"  {OK} indexed {n} sections")
        else:
            ok = False
            print(f"  {BAD} no markdown sections found")
    except Exception as e:  # noqa: BLE001 - doctor reports, never raises
        ok = False
        print(f"  {BAD} indexing failed: {e}")

    print("\n" + ("READY" if ok else "NOT READY — fix the items marked [!!]"))
    return 0 if ok else 1


def cmd_index(args: argparse.Namespace) -> int:
    from docsentry.core import retrieval
    from docsentry.core.git_ops import ensure_repo

    path = ensure_repo(fetch=not args.no_fetch)
    n = retrieval.reindex(str(path))
    print(f"Indexed {n} documentation sections from {path}")
    return 0 if n else 1


def cmd_run(args: argparse.Namespace) -> int:
    import time as _time

    from docsentry.core.git_ops import commit_message, ensure_repo, latest_commit_hash
    from docsentry.pipeline import RunOptions, run_pipeline

    problems = settings.validate_for_run()
    if problems:
        print("Not ready to run:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("\nRun `docsentry doctor` for details.", file=sys.stderr)
        return 1

    path = ensure_repo(fetch=not args.no_fetch)
    commit = args.commit or latest_commit_hash(path)
    options = RunOptions(
        # None means "use the configured default"; the flags force either way.
        # --dry-run alone could only ever turn it on, so a deployment that sets
        # dry_run=true (as render.yaml does) had no way to act from the CLI.
        dry_run=args.dry_run,
        autofix_threshold=args.autofix_threshold,
        alert_threshold=args.alert_threshold,
        max_docs_per_change=args.max_docs,
    )
    started = _time.perf_counter()
    results = run_pipeline(commit, options)
    duration_ms = int((_time.perf_counter() - started) * 1000)

    # Persist the run for the static dashboard. The Action has no database, so
    # history lives in a JSON file the dashboard reads.
    if args.history:
        from docsentry.history import append_run, make_record
        record = make_record(
            commit, results,
            commit_msg=commit_message(path, commit),
            duration_ms=duration_ms,
            trigger="action" if args.history else "manual",
            dry_run=options.resolved()["dry_run"],
            repo=settings.target_repo,
        )
        append_run(args.history, record)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"\ncommit {commit[:8]} — {len(results)} finding(s)\n")
        for r in results:
            conf = f"{r['confidence']:.0%}" if r["confidence"] else "  - "
            detail = r["change"].get("detail") or r["mismatch"] or ""
            print(f"  {r['status']:<26} {conf:>4}  {detail}")
            if r["url"]:
                print(f"  {'':<26}       {r['url']}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    print(json.dumps(settings.public_dict(), indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    uvicorn.run(
        "docsentry.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Emit the self-contained monitoring dashboard (no server, no build)."""
    from pathlib import Path

    from docsentry.dashboard_static import render_dashboard

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "dashboard.html"
    dest.write_text(render_dashboard(args.history_url), encoding="utf-8")
    print(f"Wrote {dest}")
    print(f"It reads run history from: {args.history_url}")
    print("Open it in a browser, or publish it next to a history.json file.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="docsentry",
        description="An autonomous agent that keeps documentation honest.",
    )
    p.add_argument("--version", action="version", version=f"DocSentry {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="check config, LLM and repo access")
    d.set_defaults(func=cmd_doctor)

    i = sub.add_parser("index", help="index the watched repo's documentation")
    i.add_argument("--no-fetch", action="store_true", help="skip git fetch")
    i.set_defaults(func=cmd_index)

    r = sub.add_parser("run", help="run the agent on a commit")
    r.add_argument("commit", nargs="?", help="commit SHA (default: repo HEAD)")
    dr = r.add_mutually_exclusive_group()
    dr.add_argument("--dry-run", dest="dry_run", action="store_true", default=None,
                    help="analyse but open no issues or PRs")
    dr.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                    help="open issues and PRs even if dry_run is set in the environment")
    r.add_argument("--json", action="store_true", help="machine-readable output")
    r.add_argument("--no-fetch", action="store_true", help="skip git fetch")
    r.add_argument("--autofix-threshold", type=float, metavar="0-1")
    r.add_argument("--alert-threshold", type=float, metavar="0-1")
    r.add_argument("--max-docs", type=int, metavar="N",
                   help="doc sections judged per code change")
    r.add_argument("--history", metavar="FILE",
                   help="append this run to a JSON history file for the dashboard")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("config", help="print the effective configuration")
    c.set_defaults(func=cmd_config)

    db = sub.add_parser("dashboard",
                        help="write the standalone monitoring dashboard (dashboard.html)")
    db.add_argument("--out", default=".", metavar="DIR",
                    help="directory to write dashboard.html into (default: .)")
    db.add_argument("--history-url", default="history.json", metavar="URL",
                    help="where the dashboard fetches run history (default: history.json)")
    db.set_defaults(func=cmd_dashboard)

    s = sub.add_parser("serve", help="run the API and webhook receiver")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(func=cmd_serve)

    return p


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252, which cannot encode the arrows and
    dashes in change details — printing a finding raised UnicodeEncodeError and
    took the command down. The text itself stays UTF-8 for GitHub."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # already unicode-safe, or redirected to something exotic


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    args = build_parser().parse_args(argv)
    _log(args.verbose)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001 - a CLI should not spew a traceback
        from docsentry.core.git_ops import redact
        print(f"error: {redact(e)}", file=sys.stderr)
        if args.verbose:
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
