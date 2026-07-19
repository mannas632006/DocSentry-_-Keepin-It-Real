import { useState } from "react";
import Finding from "./Finding.jsx";
import { duration, fullTime, shortSha, statusInfo, timeAgo } from "../lib/format.js";

/** Rank a run by its most consequential finding, so a collapsed row still
 *  tells you whether anything happened. */
const PRECEDENCE = [
  "error",
  "auto_fixed",
  "fix_failed_verification",
  "alerted",
  "low_confidence_skip",
  "clean",
];

function headline(results) {
  for (const status of PRECEDENCE) {
    const hit = results.find((r) => r.status === status);
    if (hit) return hit.status;
  }
  return results[0]?.status ?? "clean";
}

export default function RunCard({ run, repo, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const results = run.results ?? [];
  const top = headline(results);
  const info = statusInfo(top);
  const counts = results.reduce((acc, r) => {
    acc[r.status] = (acc[r.status] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="run card" style={{ borderLeft: `3px solid ${info.rail}` }}>
      <button
        className="run-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className={`chev ${open ? "open" : ""}`} aria-hidden="true">▶</span>

        <span className="sha" title={run.commit}>{shortSha(run.commit)}</span>

        <span className="grow truncate">
          {run.commit_msg || <span className="faint">no commit message</span>}
        </span>

        {run.dry_run && (
          <span className="badge badge-mini badge-low_confidence_skip">DRY RUN</span>
        )}

        {Object.entries(counts).map(([status, n]) => (
          <span key={status} className={`badge badge-mini badge-${status}`}>
            {statusInfo(status).label}{n > 1 ? ` ×${n}` : ""}
          </span>
        ))}

        <span className="tiny faint" title={fullTime(run.ts)} style={{ flex: "none" }}>
          {timeAgo(run.ts)}
        </span>
      </button>

      {open && (
        <div className="run-body">
          {run.error && (
            <div className="banner banner-error" style={{ marginTop: 10 }}>
              <span aria-hidden="true">⚠</span>
              <div><strong>Run failed:</strong> {run.error}</div>
            </div>
          )}

          {results.length === 0 && !run.error && (
            <p className="small muted" style={{ padding: "8px 0" }}>
              No findings recorded for this run.
            </p>
          )}

          {results.map((f, i) => (
            <Finding key={f.id ?? i} finding={f} repo={repo} commit={run.commit} />
          ))}

          <div className="finding-meta" style={{ marginTop: 10 }}>
            <span>{fullTime(run.ts)}</span>
            {run.duration_ms > 0 && <span>· took {duration(run.duration_ms)}</span>}
            <span>· triggered by {run.trigger}</span>
          </div>
        </div>
      )}
    </div>
  );
}
