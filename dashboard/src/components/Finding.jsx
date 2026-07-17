import { useState } from "react";
import { confidenceColor, inlineCode, statusInfo } from "../lib/format.js";

const isDryRun = (url) => url?.startsWith("dry-run://");

export default function Finding({ finding }) {
  const [showFix, setShowFix] = useState(false);
  const info = statusInfo(finding.status);
  const { change, doc, confidence, mismatch, suggested_fix: fix, url } = finding;
  const detail = change?.detail || mismatch || info.label;

  return (
    <div className="finding">
      <span className={`badge badge-${finding.status}`}>{info.label}</span>

      <div className="finding-main">
        <div
          className="finding-detail"
          dangerouslySetInnerHTML={{ __html: inlineCode(detail) }}
        />

        {(doc?.file || change?.file) && (
          <div className="finding-meta">
            {change?.file && <span className="mono">{change.file}</span>}
            {doc?.file && (
              <>
                <span aria-hidden="true">→</span>
                <span className="mono">
                  {doc.file}
                  {doc.heading ? ` § ${doc.heading}` : ""}
                </span>
              </>
            )}
            {change?.kind && (
              <span className="badge badge-mini badge-low_confidence_skip">
                {change.kind.replace(/_/g, " ")}
              </span>
            )}
          </div>
        )}

        {mismatch && change?.detail && (
          <div className="finding-mismatch">{mismatch}</div>
        )}

        {fix && (
          <>
            <button className="fix-toggle" onClick={() => setShowFix((v) => !v)}>
              {showFix ? "Hide suggested fix" : "Show suggested fix"}
            </button>
            {showFix && <pre className="fix">{fix}</pre>}
          </>
        )}
      </div>

      {confidence > 0 && (
        <div className="conf" title={`Model confidence: ${(confidence * 100).toFixed(0)}%`}>
          <div className="conf-bar">
            <div
              className="conf-fill"
              style={{
                width: `${Math.round(confidence * 100)}%`,
                background: confidenceColor(confidence),
              }}
            />
          </div>
          <span className="conf-text">{(confidence * 100).toFixed(0)}%</span>
        </div>
      )}

      {url && (
        isDryRun(url) ? (
          <span className="badge badge-mini badge-low_confidence_skip" title="Dry run: nothing was opened">
            DRY RUN
          </span>
        ) : (
          <a href={url} target="_blank" rel="noreferrer" className="small">
            view →
          </a>
        )
      )}
    </div>
  );
}
