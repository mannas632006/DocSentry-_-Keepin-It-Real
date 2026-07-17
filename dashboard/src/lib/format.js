/* Presentation helpers shared across components. */

export const STATUS = {
  auto_fixed:              { label: "AUTO-FIXED", rail: "var(--st-fixed-line)", tone: "fixed" },
  alerted:                 { label: "ALERT",      rail: "var(--st-alert-line)", tone: "alert" },
  clean:                   { label: "CLEAN",      rail: "var(--st-clean-line)", tone: "clean" },
  fix_failed_verification: { label: "ESCALATED",  rail: "var(--st-esc-line)",   tone: "esc" },
  low_confidence_skip:     { label: "SKIPPED",    rail: "var(--st-skip-line)",  tone: "skip" },
  no_semantic_changes:     { label: "NO CHANGES", rail: "var(--st-skip-line)",  tone: "skip" },
  no_linked_docs:          { label: "NO DOCS",    rail: "var(--st-skip-line)",  tone: "skip" },
  no_docs_indexed:         { label: "NO DOCS",    rail: "var(--st-skip-line)",  tone: "skip" },
  error:                   { label: "ERROR",      rail: "var(--st-err-line)",   tone: "err" },
};

export const statusInfo = (s) =>
  STATUS[s] ?? { label: (s || "unknown").toUpperCase().replace(/_/g, " "),
                 rail: "var(--st-skip-line)", tone: "skip" };

/** Filterable statuses, in the order a reader cares about them. */
export const FILTERABLE = [
  "auto_fixed",
  "alerted",
  "fix_failed_verification",
  "clean",
  "low_confidence_skip",
  "error",
];

export function timeAgo(ts) {
  if (!ts) return "never";
  const secs = Math.floor(Date.now() / 1000 - ts);
  if (secs < 5) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

export const fullTime = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "");

export const shortSha = (sha) => (sha || "").slice(0, 7) || "unknown";

export function duration(ms) {
  if (!ms) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function confidenceColor(c) {
  if (c >= 0.85) return "var(--st-fixed-line)";
  if (c >= 0.5) return "var(--st-alert-line)";
  return "var(--st-skip-line)";
}

/** Render `backticked` spans as <code>. Escapes first — content is model
 *  output and repo text, so it must never be trusted as markup. */
export function inlineCode(text) {
  if (!text) return "";
  const escaped = String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return escaped.replace(/`([^`]+)`/g, "<code>$1</code>");
}
