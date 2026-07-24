/** Formats an ISO date string ("2026-07-20") as "July 20, 2026". */
export function formatDate(isoDate) {
  if (!isoDate) return isoDate;
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return isoDate;
  const date = new Date(year, month - 1, day);
  return date.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

/** Formats an ISO date range as "July 14, 2026 to July 20, 2026". */
export function formatDateRange(startIso, endIso) {
  return `${formatDate(startIso)} to ${formatDate(endIso)}`;
}
