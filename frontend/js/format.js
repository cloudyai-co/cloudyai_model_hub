/**
 * Display formatting. Mirrors the PDF report (backend/report.py) so the web and print views agree.
 */

export const EMPTY = "—";

const INTEGER = new Intl.NumberFormat("en-US");
const COMPACT = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

const isFiniteNumber = (value) => typeof value === "number" && Number.isFinite(value);

export function formatInt(value) {
  return isFiniteNumber(value) ? INTEGER.format(Math.round(value)) : EMPTY;
}

/** Short counts for downloads and likes: 8.1M, 2.4K, 987. */
export function formatCompact(value) {
  return isFiniteNumber(value) ? COMPACT.format(value) : EMPTY;
}

/** Byte sizes in binary units, to match the PDF: 512 B, 14.2 GB. */
export function formatBytes(value) {
  if (!isFiniteNumber(value) || value < 0) return EMPTY;
  let amount = value;
  for (const unit of ["B", "KB", "MB", "GB"]) {
    if (amount < 1024) return unit === "B" ? `${Math.round(amount)} B` : `${amount.toFixed(1)} ${unit}`;
    amount /= 1024;
  }
  return `${amount.toFixed(1)} TB`;
}

/** Gigabyte estimates from the capacity model. */
export function formatGigabytes(value) {
  if (!isFiniteNumber(value)) return EMPTY;
  return `${value.toFixed(value >= 100 ? 0 : 1)} GB`;
}

/** Accelerator memory as spec sheets write it: 80 GB, 192 GB. */
export function formatVram(value) {
  return isFiniteNumber(value) && value > 0 ? `${Math.round(value)} GB` : EMPTY;
}

/** Parameter counts: 7.62 B, 46.7 B, 350 M. */
export function formatParameters(count) {
  if (!isFiniteNumber(count) || count <= 0) return EMPTY;
  if (count >= 1e9) return `${(count / 1e9).toFixed(2)} B`;
  if (count >= 1e6) return `${(count / 1e6).toFixed(1)} M`;
  return INTEGER.format(count);
}

/** ISO timestamps as a date: 2025-01-12. */
export function formatDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : EMPTY;
}

/** ISO timestamps as a UTC date and time: 2026-10-09 12:00 UTC. */
export function formatTimestamp(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return EMPTY;
  return `${value.slice(0, 10)} ${value.slice(11, 16)} UTC`;
}

/** Shortened digest or commit id: 9f1a0c3b2d4e… */
export function shortHash(value, length = 12) {
  return typeof value === "string" && value.length > 0 ? `${value.slice(0, length)}…` : EMPTY;
}

export function pluralize(count, singular, plural = `${singular}s`) {
  return `${formatInt(count)} ${count === 1 ? singular : plural}`;
}

export const LEVEL_LABELS = Object.freeze({ strong: "Strong", partial: "Partial", sparse: "Sparse" });

export function levelLabel(level) {
  return LEVEL_LABELS[level] ?? EMPTY;
}

/** Map `hf:weightDtypes` text ("BF16:7615616512,F32:12") to [{ dtype, count }] sorted by size. */
export function parseWeightDtypes(value) {
  if (typeof value !== "string" || !value) return [];
  return value
    .split(",")
    .map((part) => {
      const [dtype, count] = part.split(":");
      return { dtype, count: Number(count) };
    })
    .filter((item) => item.dtype && Number.isFinite(item.count))
    .sort((a, b) => b.count - a.count);
}
