import { useEffect, useState } from "react";

const API = "http://localhost:8000";

const STATUS_STYLE = {
  auto_fixed: { label: "AUTO-FIXED", bg: "#14532d", fg: "#86efac" },
  alerted: { label: "ALERT", bg: "#7c2d12", fg: "#fdba74" },
  clean: { label: "CLEAN", bg: "#1e3a8a", fg: "#93c5fd" },
  fix_failed_verification: { label: "ESCALATED", bg: "#713f12", fg: "#fde047" },
  low_confidence_skip: { label: "SKIPPED", bg: "#374151", fg: "#d1d5db" },
  no_semantic_changes: { label: "NO CHANGES", bg: "#374151", fg: "#d1d5db" },
};

function Badge({ status }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.low_confidence_skip;
  return (
    <span style={{ background: s.bg, color: s.fg, padding: "2px 10px",
                   borderRadius: 999, fontSize: 12, fontWeight: 700 }}>
      {s.label}
    </span>
  );
}

export default function App() {
  const [runs, setRuns] = useState([]);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    const load = () => {
      fetch(`${API}/api/runs`).then(r => r.json()).then(setRuns);
      fetch(`${API}/api/stats`).then(r => r.json()).then(setStats);
    };
    load();
    const t = setInterval(load, 5000);        // poll every 5s
    return () => clearInterval(t);
  }, []);

  return (
    <div style={{ fontFamily: "system-ui", maxWidth: 860, margin: "40px auto",
                  padding: "0 16px", color: "#e5e7eb", background: "#0b0f14" }}>
      <h1 style={{ letterSpacing: -1 }}>🛡️ DocSentry</h1>
      <p style={{ color: "#9ca3af" }}>Documentation drift, caught live.</p>

      {stats && (
        <div style={{ display: "flex", gap: 12, margin: "24px 0" }}>
          {[["Runs", stats.total_runs], ["Auto-fixed", stats.auto_fixed],
            ["Alerts", stats.alerted], ["Clean", stats.clean]].map(([k, v]) => (
            <div key={k} style={{ flex: 1, background: "#111827",
                                  borderRadius: 12, padding: 16 }}>
              <div style={{ fontSize: 28, fontWeight: 800 }}>{v}</div>
              <div style={{ color: "#9ca3af", fontSize: 13 }}>{k}</div>
            </div>
          ))}
        </div>
      )}

      {runs.map(run => (
        <div key={run.id} style={{ background: "#111827", borderRadius: 12,
                                   padding: 16, marginBottom: 12 }}>
          <div style={{ color: "#9ca3af", fontSize: 12, marginBottom: 8 }}>
            commit <code>{run.commit?.slice(0, 7)}</code> ·{" "}
            {new Date(run.ts * 1000).toLocaleString()}
          </div>
          {run.results.map((r, i) => (
            <div key={i} style={{ display: "flex", gap: 10, alignItems: "center",
                                  padding: "6px 0" }}>
              <Badge status={r.status} />
              <span style={{ fontSize: 14 }}>{r.change ?? r.status}</span>
              {(r.pr || r.issue) && (
                <a href={r.pr ?? r.issue} target="_blank" rel="noreferrer"
                   style={{ color: "#60a5fa", fontSize: 13 }}>view →</a>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
