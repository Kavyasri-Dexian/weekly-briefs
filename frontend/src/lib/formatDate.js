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

/** Formats a full ISO timestamp ("2026-07-24T12:07:46.736222+00:00") as
 * "24-Jul-2026, 12:07 UTC". */
export function formatDateTime(isoDateTime) {
  if (!isoDateTime) return isoDateTime;
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return isoDateTime;
  const datePart = date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  const timePart = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  return `${datePart}, ${timePart} UTC`;
}
