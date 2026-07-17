import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError, getApiBase } from "./api.js";
import RunCard from "./components/RunCard.jsx";
import SettingsPanel from "./components/SettingsPanel.jsx";
import StatsBar from "./components/StatsBar.jsx";
import TriggerPanel from "./components/TriggerPanel.jsx";
import { useTheme } from "./hooks/useTheme.js";
import { FILTERABLE, statusInfo, timeAgo } from "./lib/format.js";

const PAGE_SIZE = 20;
const REFRESH_CHOICES = [
  { value: 0, label: "Off" },
  { value: 5, label: "5s" },
  { value: 15, label: "15s" },
  { value: 60, label: "1m" },
];
const THEME_ICON = { auto: "◐", dark: "☾", light: "☀" };

export default function App() {
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState(null);
  const [health, setHealth] = useState(null);
  const [config, setConfig] = useState(null);

  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(0);

  const [refreshSecs, setRefreshSecs] = useState(15);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [panel, setPanel] = useState(null);   // "trigger" | "settings" | null
  const [apiBase, setApiBaseState] = useState(getApiBase());

  const { theme, cycle } = useTheme();
  const abortRef = useRef(null);

  // Debounce the search box so typing does not fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(query);
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback(async ({ quiet = false } = {}) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    if (!quiet) setLoading(true);
    try {
      const [runsRes, statsRes] = await Promise.all([
        api.runs({ limit: PAGE_SIZE, offset: page * PAGE_SIZE, status, q: debounced },
                 ctrl.signal),
        api.stats(ctrl.signal),
      ]);
      setRuns(runsRes.runs);
      setTotal(runsRes.total);
      setStats(statsRes);
      setError(null);
    } catch (e) {
      if (e.name === "AbortError") return;
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, [page, status, debounced]);

  // Health and config change rarely; fetch them separately from the poll loop.
  const loadMeta = useCallback(async () => {
    try {
      const [h, c] = await Promise.all([api.health(), api.config()]);
      setHealth(h);
      setConfig(c);
    } catch {
      setHealth(null);
      setConfig(null);
    }
  }, [apiBase]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadMeta(); }, [loadMeta]);

  useEffect(() => {
    if (!refreshSecs) return;
    const t = setInterval(() => load({ quiet: true }), refreshSecs * 1000);
    return () => clearInterval(t);
  }, [refreshSecs, load]);

  const onSettingsChanged = () => {
    setApiBaseState(getApiBase());
    loadMeta();
    load();
  };

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtering = !!(status || debounced);

  const healthPill = useMemo(() => {
    if (!health) return { cls: "dot-error", text: "API unreachable" };
    if (!health.ready) return { cls: "dot-warn", text: "Not configured" };
    if (!health.llm?.reachable) return { cls: "dot-warn", text: "LLM unreachable" };
    return { cls: "dot-ok dot-live", text: `${health.llm.provider} · ${health.llm.model}` };
  }, [health]);

  return (
    <div className="shell">
      <header className="masthead">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">🛡️</span>
          <div>
            <h1>DocSentry</h1>
            <p>Documentation drift, caught live.</p>
          </div>
        </div>

        <div className="header-actions">
          <span className="pill" title={health?.llm?.error || health?.llm?.base_url || ""}>
            <span className={`dot ${healthPill.cls}`} />
            {healthPill.text}
          </span>

          {config?.target_repo && (
            <a
              className="pill"
              href={`https://github.com/${config.target_repo}`}
              target="_blank"
              rel="noreferrer"
              style={{ color: "inherit" }}
            >
              <span aria-hidden="true">⎇</span>
              {config.target_repo}
            </a>
          )}

          {config?.dry_run && (
            <span className="pill" title="Server-wide dry run: no issues or PRs will be opened">
              <span className="dot dot-warn" />
              Dry run
            </span>
          )}

          <button
            className="btn btn-icon"
            onClick={cycle}
            title={`Theme: ${theme}. Click to change.`}
            aria-label={`Theme: ${theme}`}
          >
            {THEME_ICON[theme]}
          </button>

          <button
            className="btn"
            onClick={() => setPanel(panel === "settings" ? null : "settings")}
            aria-expanded={panel === "settings"}
          >
            ⚙ Settings
          </button>

          <button
            className="btn btn-primary"
            onClick={() => setPanel(panel === "trigger" ? null : "trigger")}
            aria-expanded={panel === "trigger"}
          >
            ▶ Run agent
          </button>
        </div>
      </header>

      {error && (
        <div className="banner banner-error">
          <span aria-hidden="true">⚠</span>
          <div>
            <strong>{error}</strong>
            <div className="tiny" style={{ marginTop: 4 }}>
              API: <code>{apiBase}</code> — change it in Settings.
            </div>
          </div>
        </div>
      )}

      {health && !health.ready && health.problems?.length > 0 && (
        <div className="banner banner-warn">
          <span aria-hidden="true">⚠</span>
          <div>
            <strong>The agent is not ready to run.</strong>
            <ul>{health.problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        </div>
      )}

      {panel === "trigger" && (
        <TriggerPanel
          config={config}
          onQueued={() => setTimeout(() => load({ quiet: true }), 1200)}
          onClose={() => setPanel(null)}
        />
      )}
      {panel === "settings" && (
        <SettingsPanel
          config={config}
          health={health}
          onChanged={onSettingsChanged}
          onClose={() => setPanel(null)}
        />
      )}

      <StatsBar
        stats={stats}
        activeStatus={status}
        onFilter={(s) => { setStatus(s); setPage(0); }}
        loading={loading}
      />

      <div className="panel">
        <div className="filters">
          <div className="search">
            <span className="search-icon" aria-hidden="true">⌕</span>
            <input
              className="input"
              placeholder="Search commits, files, findings…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search runs"
            />
          </div>

          <select
            className="select"
            value={status}
            onChange={(e) => { setStatus(e.target.value); setPage(0); }}
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            {FILTERABLE.map((s) => (
              <option key={s} value={s}>{statusInfo(s).label}</option>
            ))}
          </select>

          <select
            className="select"
            value={refreshSecs}
            onChange={(e) => setRefreshSecs(Number(e.target.value))}
            aria-label="Auto-refresh interval"
            title="Auto-refresh"
          >
            {REFRESH_CHOICES.map((c) => (
              <option key={c.value} value={c.value}>↻ {c.label}</option>
            ))}
          </select>

          <button className="btn" onClick={() => load()} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>

          {filtering && (
            <button
              className="btn btn-sm"
              onClick={() => { setStatus(""); setQuery(""); setPage(0); }}
            >
              Clear filters
            </button>
          )}

          <span className="spacer" />
          <span className="small muted">
            {total} run{total === 1 ? "" : "s"}
            {filtering ? " matching" : ""}
          </span>
        </div>
      </div>

      {loading && runs.length === 0 && (
        <>
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </>
      )}

      {!loading && runs.length === 0 && (
        <div className="card empty">
          <div className="empty-mark" aria-hidden="true">{filtering ? "⌕" : "🛡️"}</div>
          <h3>{filtering ? "Nothing matches those filters" : "No runs yet"}</h3>
          <p>
            {filtering
              ? "Try clearing the search or picking a different status."
              : "Push a commit to the watched repo, or use “Run agent” to analyse " +
                "its current HEAD. Findings will show up here."}
          </p>
          {filtering && (
            <button
              className="btn"
              style={{ marginTop: 14 }}
              onClick={() => { setStatus(""); setQuery(""); setPage(0); }}
            >
              Clear filters
            </button>
          )}
        </div>
      )}

      {runs.map((run, i) => (
        <RunCard key={run.id} run={run} defaultOpen={i === 0 && page === 0} />
      ))}

      {pages > 1 && (
        <div className="pager">
          <button className="btn btn-sm" disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}>
            ← Newer
          </button>
          <span>Page {page + 1} of {pages}</span>
          <button className="btn btn-sm" disabled={page >= pages - 1}
                  onClick={() => setPage((p) => p + 1)}>
            Older →
          </button>
        </div>
      )}

      <footer className="footer">
        <span>
          DocSentry {health?.version ? `v${health.version}` : ""} · last run{" "}
          {stats?.last_run_ts ? timeAgo(stats.last_run_ts) : "never"}
        </span>
        <span>
          <a href={`${apiBase}/docs`} target="_blank" rel="noreferrer">API docs</a>
          {" · "}
          <a href="https://github.com/mannas632006/DocSentry-_-Keepin-It-Real"
             target="_blank" rel="noreferrer">Source</a>
        </span>
      </footer>
    </div>
  );
}
