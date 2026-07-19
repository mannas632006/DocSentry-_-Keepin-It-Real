import { useState } from "react";
import { api, ApiError, getApiBase, getToken, setApiBase, setToken } from "../api.js";

const yesNo = (v) => (v ? "yes" : "no");

export default function SettingsPanel({ config, health, onChanged, onClose }) {
  const [base, setBase] = useState(getApiBase());
  const [token, setTok] = useState(getToken());
  const [saved, setSaved] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState(null);

  function save(e) {
    e.preventDefault();
    setApiBase(base);
    setToken(token);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
    onChanged?.();
  }

  async function clearHistory() {
    if (!confirm("Delete all run history and the alert dedup log? Issues and PRs already opened on GitHub are not affected.")) {
      return;
    }
    setClearing(true);
    setError(null);
    try {
      await api.clearRuns();
      onChanged?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="panel">
      <div className="row-between" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Settings</h2>
        <button className="btn btn-sm" onClick={onClose}>Close</button>
      </div>

      <form onSubmit={save}>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="api">API URL</label>
            <input
              id="api"
              className="input"
              value={base}
              onChange={(e) => setBase(e.target.value)}
              placeholder="https://docsentry-api.onrender.com"
            />
            <span className="hint">
              Stored in this browser, so the dashboard can be repointed without a rebuild.
            </span>
          </div>

          <div className="field">
            <label htmlFor="tok">Admin token</label>
            <input
              id="tok"
              className="input"
              type="password"
              value={token}
              onChange={(e) => setTok(e.target.value)}
              placeholder={config?.admin_enabled ? "required to trigger runs" : "server has none set"}
              autoComplete="off"
            />
            <span className="hint">
              Must match <code>admin_token</code> on the server. Kept in this browser only.
            </span>
          </div>
        </div>

        <div className="row" style={{ marginTop: 14 }}>
          <button type="submit" className="btn btn-primary">Save</button>
          {saved && <span className="small" style={{ color: "var(--st-fixed-fg)" }}>Saved.</span>}
        </div>
      </form>

      <h2 style={{ marginTop: 24 }}>Server configuration</h2>
      {config ? (
        <dl className="kv">
          <dt>Watched repo</dt>
          <dd>
            {config.target_repo ? (
              <a href={`https://github.com/${config.target_repo}`} target="_blank" rel="noreferrer">
                {config.target_repo}
              </a>
            ) : <span className="faint">not set</span>}
          </dd>

          <dt>LLM</dt>
          <dd>{config.llm_provider} · {config.llm_model}</dd>

          <dt>Endpoint</dt>
          <dd className="truncate" title={config.llm_base_url}>{config.llm_base_url}</dd>

          <dt>Reachable</dt>
          <dd>
            {health?.llm
              ? (health.llm.reachable
                  ? <span style={{ color: "var(--st-fixed-fg)" }}>yes</span>
                  : <span style={{ color: "var(--st-err-fg)" }}>no — {health.llm.error}</span>)
              : "—"}
          </dd>

          <dt>Retrieval</dt>
          <dd>{config.retrieval_backend}</dd>

          <dt>Auto-fix at</dt>
          <dd>{(config.autofix_threshold * 100).toFixed(0)}%</dd>

          <dt>Alert at</dt>
          <dd>{(config.alert_threshold * 100).toFixed(0)}%</dd>

          <dt>Docs per change</dt>
          <dd>{config.max_docs_per_change}</dd>

          <dt>Global dry run</dt>
          <dd>{yesNo(config.dry_run)}</dd>

          <dt>Credentials</dt>
          <dd>
            github token {yesNo(config.github_token_set)} · llm key {yesNo(config.llm_api_key_set)}
            {" · "}admin {yesNo(config.admin_enabled)}
          </dd>
        </dl>
      ) : (
        <p className="small muted">Not available — the API is unreachable.</p>
      )}

      <p className="tiny faint" style={{ marginTop: 10 }}>
        These are read-only: they come from the server's environment. Change
        them where the API is deployed, not here.
      </p>

      <h2 style={{ marginTop: 24 }}>Danger zone</h2>
      {error && (
        <div className="banner banner-error"><span aria-hidden="true">⚠</span><div>{error}</div></div>
      )}
      <div className="row wrap">
        <button
          className="btn btn-danger"
          onClick={clearHistory}
          disabled={clearing || !config?.admin_enabled || !getToken()}
        >
          {clearing ? "Clearing…" : "Clear run history"}
        </button>
        <span className="tiny faint">
          Wipes local history and the dedup log. Issues already filed on GitHub stay.
        </span>
      </div>
    </div>
  );
}
