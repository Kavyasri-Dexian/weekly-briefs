import { useState } from "react";

function parseBrief(text) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const [lead, ...points] = lines;
  return { lead, points };
}

export default function Narrative({ briefEn, briefHi }) {
  const [lang, setLang] = useState("en");
  const text = lang === "en" ? briefEn : briefHi;
  const { lead, points } = parseBrief(text);

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
      {lead ? <p className="narrative-lead">{lead}</p> : null}
      <ul className="narrative-list">
        {points.map((point, i) => (
          <li key={i}>{point}</li>
        ))}
      </ul>
    </section>
  );
}
