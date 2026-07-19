import { useState } from "react";
import { api, ApiError, getToken } from "../api.js";

/** Run the agent on demand, with one-off overrides that do not mutate server
 *  config. Handy for demoing a threshold without a redeploy. */
export default function TriggerPanel({ config, onQueued, onClose }) {
  const [commit, setCommit] = useState("");
  const [dryRun, setDryRun] = useState(true);
  const [advanced, setAdvanced] = useState(false);
  const [autofix, setAutofix] = useState("");
  const [alert, setAlert] = useState("");
  const [maxDocs, setMaxDocs] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [ok, setOk] = useState(null);

  const hasToken = !!getToken();
  const adminEnabled = config?.admin_enabled;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      const body = { dry_run: dryRun };
      if (commit.trim()) body.commit = commit.trim();
      if (advanced) {
        if (autofix !== "") body.autofix_threshold = Number(autofix);
        if (alert !== "") body.alert_threshold = Number(alert);
        if (maxDocs !== "") body.max_docs_per_change = Number(maxDocs);
      }
      const res = await api.analyze(body);
      setOk(`Queued ${res.queued.slice(0, 7)}${dryRun ? " (dry run)" : ""}.`);
      onQueued?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <div className="row-between" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Run the agent</h2>
        <button className="btn btn-sm" onClick={onClose}>Close</button>
      </div>

      {!adminEnabled && (
        <div className="banner banner-warn">
          <span aria-hidden="true">⚠</span>
          <div>
            Write endpoints are disabled because the server has no{" "}
            <code>admin_token</code> set. Set one in the server environment and
            paste it into Settings to enable this.
          </div>
        </div>
      )}

      {adminEnabled && !hasToken && (
        <div className="banner banner-warn">
          <span aria-hidden="true">🔑</span>
          <div>Add your admin token in Settings before triggering a run.</div>
        </div>
      )}

      <form onSubmit={submit}>
        <div className="grid-2" style={{ marginBottom: 12 }}>
          <div className="field">
            <label htmlFor="commit">Commit</label>
            <input
              id="commit"
              className="input"
              placeholder="blank = repo HEAD"
              value={commit}
              onChange={(e) => setCommit(e.target.value)}
            />
            <span className="hint">Full or short SHA from {config?.target_repo || "the watched repo"}.</span>
          </div>

          <div className="field">
            <label>Side effects</label>
            <label className="check" style={{ marginTop: 6 }}>
              <input
                type="checkbox"
                checked={dryRun}
                onChange={(e) => setDryRun(e.target.checked)}
              />
              Dry run
            </label>
            <span className="hint">
              {dryRun
                ? "Analyse only — no issues or PRs will be opened."
                : "This will open real issues or PRs on the repo."}
            </span>
          </div>
        </div>

        <button
          type="button"
          className="fix-toggle"
          onClick={() => setAdvanced((v) => !v)}
        >
          {advanced ? "Hide overrides" : "Override thresholds for this run"}
        </button>

        {advanced && (
          <div className="grid-2" style={{ marginTop: 10, marginBottom: 12 }}>
            <div className="field">
              <label htmlFor="af">Auto-fix at</label>
              <input
                id="af" className="input" type="number" step="0.05" min="0" max="1"
                placeholder={config?.autofix_threshold ?? "0.85"}
                value={autofix}
                onChange={(e) => setAutofix(e.target.value)}
              />
              <span className="hint">Confidence ≥ this opens a PR.</span>
            </div>
            <div className="field">
              <label htmlFor="al">Alert at</label>
              <input
                id="al" className="input" type="number" step="0.05" min="0" max="1"
                placeholder={config?.alert_threshold ?? "0.50"}
                value={alert}
                onChange={(e) => setAlert(e.target.value)}
              />
              <span className="hint">Confidence ≥ this opens an issue.</span>
            </div>
            <div className="field">
              <label htmlFor="md">Docs per change</label>
              <input
                id="md" className="input" type="number" min="1" max="10"
                placeholder={config?.max_docs_per_change ?? "1"}
                value={maxDocs}
                onChange={(e) => setMaxDocs(e.target.value)}
              />
              <span className="hint">Sections judged per code change.</span>
            </div>
          </div>
        )}

        {error && (
          <div className="banner banner-error" style={{ marginTop: 12 }}>
            <span aria-hidden="true">⚠</span><div>{error}</div>
          </div>
        )}
        {ok && (
          <div className="banner banner-info" style={{ marginTop: 12 }}>
            <span aria-hidden="true">✓</span><div>{ok} Results appear below once it finishes.</div>
          </div>
        )}

        <div className="row" style={{ marginTop: 14 }}>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy || !adminEnabled || !hasToken}
          >
            {busy ? "Queuing…" : dryRun ? "Run (dry)" : "Run for real"}
          </button>
          {!dryRun && (
            <span className="tiny" style={{ color: "var(--st-alert-fg)" }}>
              This can open issues or PRs on {config?.target_repo}.
            </span>
          )}
        </div>
      </form>
    </div>
  );
}
