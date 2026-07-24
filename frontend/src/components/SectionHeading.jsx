/** Numbered section header used across the report panels (masthead-style
 * "01 Section title" register), reused instead of duplicating the markup
 * in every panel component. */
export default function SectionHeading({ n, title, tag }) {
  return (
    <div className="sec-head">
      <span className="sec-num">{n}</span>
      <h2 className="sec-title">{title}</h2>
      {tag ? <span className="sec-tag">{tag}</span> : null}
    </div>
  );
}
