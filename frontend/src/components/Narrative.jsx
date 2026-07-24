import { useState } from "react";

function parseBrief(text) {
  // Body paragraphs are blank-line separated (see pipeline.py narrate_english/
  // narrate_hindi and _clean_model_paragraphs) — title is its own leading
  // paragraph, dropped here since App.jsx already renders it via the masthead.
  const paragraphs = text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  const [, ...body] = paragraphs;
  return body.length ? body : paragraphs;
}

const NUMBER_RE = /(\d[\d,]*\.?\d*%?)/g;

/** Bolds numeric tokens within a paragraph for the "board report" register
 * (mirrors the reference design's <b> around key figures) without using
 * dangerouslySetInnerHTML — the text is our own generated prose, but this
 * keeps rendering to plain React nodes regardless. String.split() with a
 * capturing group interleaves the matched numbers at odd indices, so no
 * separate regex.test() pass is needed — reusing a `g`-flagged regex across
 * repeated .test() calls would silently desync via its own lastIndex. */
function withBoldNumbers(text) {
  return text.split(NUMBER_RE).map((part, i) =>
    i % 2 === 1 ? <b key={i}>{part}</b> : <span key={i}>{part}</span>
  );
}

function ScoreBadge({ meta }) {
  if (!meta || meta.accuracy_pct == null) return null;
  const good = meta.accuracy_pct >= 99.9;
  return (
    <div className="score-badge" title={meta.confidence || ""}>
      <span className={`score-pill ${good ? "score-good" : "score-warn"}`}>
        {meta.accuracy_pct}% numbers verified
      </span>
    </div>
  );
}

export default function Narrative({ briefEn, briefHi, narrationMeta }) {
  const [lang, setLang] = useState("en");
  const text = lang === "en" ? briefEn : briefHi;
  const paragraphs = parseBrief(text);
  const meta = narrationMeta?.[lang];

  return (
    <div className="narr">
      <div className="narr-h">
        <span>Executive Narrative</span>
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
      {paragraphs.map((p, i) => (
        <p key={i}>{withBoldNumbers(p)}</p>
      ))}
    </div>
  );
}
