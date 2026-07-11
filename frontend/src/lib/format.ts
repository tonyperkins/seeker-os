/**
 * Human-readable formatting for currency, duration, and token counts.
 * Format at render only — never change underlying stored values.
 */

/**
 * Format a USD amount. Always shows 2 decimal places.
 * - $0.00 for zero (not six decimals)
 * - <$0.01 for sub-cent values
 * - $X.XX for everything else
 */
export function formatCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n === 0) return "$0.00";
  if (n < 0.01 && n > 0) return "<$0.01";
  return `$${n.toFixed(2)}`;
}

/**
 * Format a duration in milliseconds.
 * - < 1000ms: "123ms"
 * - < 60000ms: "12.3s"
 * - >= 60000ms: "2m 05s"
 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

/**
 * Format a token count with K/M suffixes.
 * - < 1000: raw number
 * - < 1M: "443.8K"
 * - >= 1M: "1.2M"
 */
export function formatTokens(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

/**
 * Check if all models across all providers are free-tier (both input and
 * output $/Mtok are 0). A model with null pricing is not considered free
 * (it's unconfigured, not free).
 */
export function isFreeTierOnly(
  providers: { models: { input_price_per_mtok: number | null; output_price_per_mtok: number | null }[] }[],
): boolean {
  const allModels = providers.flatMap((p) => p.models);
  if (allModels.length === 0) return false;
  return allModels.every(
    (m) =>
      m.input_price_per_mtok != null &&
      m.input_price_per_mtok === 0 &&
      m.output_price_per_mtok != null &&
      m.output_price_per_mtok === 0,
  );
}
