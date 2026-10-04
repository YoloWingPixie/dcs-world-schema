/**
 * Transport packing for record JSON: arrays of three or more objects become
 * `{ $c: columns, $r: rows }`, with one level of all-scalar nested objects flattened into
 * `[parent, key]` columns. Cuts airbase stands, aircraft stations and the like by a third.
 * `null` cells mean "absent"; unpack restores the original shape minus explicit nulls.
 */

type Json = Record<string, unknown>;
type Column = string | [string, string];
export type Packed = { $c: Column[]; $r: unknown[][] };

const isObject = (v: unknown): v is Json =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const isScalar = (v: unknown) => v === null || typeof v !== "object";

function isPacked(v: unknown): v is Packed {
  return isObject(v) && Array.isArray(v.$c) && Array.isArray(v.$r) && Object.keys(v).length === 2;
}

export function pack(value: unknown): unknown {
  if (Array.isArray(value)) {
    if (value.length >= 3 && value.every(isObject)) {
      const columns: Column[] = [];
      const seen = new Set<string>();
      const add = (c: Column) => {
        const k = typeof c === "string" ? c : `${c[0]}\u0000${c[1]}`;
        if (!seen.has(k)) {
          seen.add(k);
          columns.push(c);
        }
      };
      // A nested object flattens only when it is all-scalar in every row.
      const flatten = new Set<string>();
      const nested = new Set<string>();
      for (const row of value as Json[]) {
        for (const [k, v] of Object.entries(row)) {
          if (isObject(v) && Object.values(v).every(isScalar) && Object.keys(v).length) {
            flatten.add(k);
          } else if (v !== undefined) nested.add(k);
        }
      }
      for (const k of nested) flatten.delete(k);
      for (const row of value as Json[]) {
        for (const [k, v] of Object.entries(row)) {
          if (flatten.has(k) && isObject(v)) for (const k2 of Object.keys(v)) add([k, k2]);
          else add(k);
        }
      }
      const rows = (value as Json[]).map((row) =>
        columns.map((c) => {
          const v = typeof c === "string" ? row[c] : (row[c[0]] as Json | undefined)?.[c[1]];
          return v === undefined ? null : pack(v);
        }),
      );
      return { $c: columns, $r: rows } satisfies Packed;
    }
    return value.map(pack);
  }
  if (isObject(value)) {
    const out: Json = {};
    for (const [k, v] of Object.entries(value)) out[k] = pack(v);
    return out;
  }
  return value;
}

export function unpack(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(unpack);
  if (isPacked(value)) {
    return value.$r.map((row) => {
      const out: Json = {};
      value.$c.forEach((c, i) => {
        const cell = row[i];
        if (cell === null || cell === undefined) return;
        if (typeof c === "string") out[c] = unpack(cell);
        else {
          const parent = isObject(out[c[0]]) ? (out[c[0]] as Json) : {};
          parent[c[1]] = cell;
          out[c[0]] = parent;
        }
      });
      return out;
    });
  }
  if (isObject(value)) {
    const out: Json = {};
    for (const [k, v] of Object.entries(value)) out[k] = unpack(v);
    return out;
  }
  return value;
}
