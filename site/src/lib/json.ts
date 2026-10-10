/** A parsed JSON object. */
export type Json = Record<string, unknown>;

/** Whether a stored value counts as one: not absent, null or an empty list. */
export function present(value: unknown): boolean {
  return value !== undefined && value !== null && !(Array.isArray(value) && value.length === 0);
}

/** A plain object (not null, not an array). */
export function isRecord(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
