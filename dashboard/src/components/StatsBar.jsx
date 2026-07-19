import { statusInfo } from "../lib/format.js";

const CARDS = [
  { key: "total_runs", label: "Runs", status: null },
  { key: "auto_fixed", label: "Auto-fixed", status: "auto_fixed" },
  { key: "alerted", label: "Alerts", status: "alerted" },
  { key: "escalated", label: "Escalated", status: "fix_failed_verification" },
  { key: "clean", label: "Clean", status: "clean" },
  { key: "skipped", label: "Skipped", status: "low_confidence_skip" },
];

/** Stat tiles double as status filters — clicking one is the fastest way to
 *  answer "show me the alerts". */
export default function StatsBar({ stats, activeStatus, onFilter, loading }) {
  if (loading && !stats) {
    return (
      <div className="stats">
        {CARDS.map((c) => (
          <div key={c.key} className="skeleton" style={{ height: 74, margin: 0 }} />
        ))}
      </div>
    );
  }
  if (!stats) return null;

  return (
    <div className="stats">
      {CARDS.map((c) => {
        const selectable = c.status !== null;
        const active = selectable && activeStatus === c.status;
        const rail = c.status ? statusInfo(c.status).rail : "var(--accent)";
        return (
          <button
            key={c.key}
            className="stat"
            style={{ "--rail": rail }}
            aria-pressed={active}
            onClick={() => onFilter(selectable && !active ? c.status : "")}
            title={selectable
              ? (active ? "Clear this filter" : `Show only runs with ${c.label.toLowerCase()}`)
              : "Show all runs"}
          >
            <div className="stat-value">{stats[c.key] ?? 0}</div>
            <div className="stat-label">{c.label}</div>
          </button>
        );
      })}
    </div>
  );
}
