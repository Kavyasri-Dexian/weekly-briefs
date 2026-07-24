import { useState } from "react";

function parseBrief(text) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const [lead, ...points] = lines;
  return { lead, points };
}

function ScoreBadge({ meta }) {
  if (!meta || meta.accuracy_pct == null) return null;
  const good = meta.accuracy_pct >= 99.9;
  return (
    <div className="score-badge" title={meta.confidence || ""}>
      <span className={`score-pill ${good ? "score-good" : "score-warn"}`}>
        {meta.accuracy_pct}% numbers verified
      </span>
      <span className="score-detail">
        {meta.numbers_verified}/{meta.numbers_checked} checked · {meta.used_model ? "model draft" : "template"}
        {meta.used_model ? ` (${meta.attempts} attempt${meta.attempts === 1 ? "" : "s"})` : ""}
      </span>
    </div>
  );
}

export default function Narrative({ briefEn, briefHi, narrationMeta }) {
  const [lang, setLang] = useState("en");
  const text = lang === "en" ? briefEn : briefHi;
  const { lead, points } = parseBrief(text);
  const meta = narrationMeta?.[lang];

  return (
    <section className="panel narrative-panel">
      <div className="narrative-header">
        <h2 className="panel-title narrative-title">Executive Summary</h2>
        <div className="lang-toggle" role="tablist" aria-label="Language">
          <button
            role="tab"
            aria-selected={lang === "en"}
            className={`lang-btn ${lang === "en" ? "lang-btn-active" : ""}`}
            onClick={() => setLang("en")}
          >
            English
          </button>
          <button
            role="tab"
            aria-selected={lang === "hi"}
            className={`lang-btn ${lang === "hi" ? "lang-btn-active" : ""}`}
            onClick={() => setLang("hi")}
          >
            हिन्दी
          </button>
        </div>
      </div>
      <ScoreBadge meta={meta} />
      {lead ? <p className="narrative-lead">{lead}</p> : null}
      <ul className="narrative-list">
        {points.map((point, i) => (
          <li key={i}>{point}</li>
        ))}
      </ul>
    </section>
  );
}
