/** A parsed JSON object. */
export type Json = Record<string, unknown>;

/** A plain object (not null, not an array). */
export function isRecord(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
