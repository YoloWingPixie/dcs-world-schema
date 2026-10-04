/**
 * The database's `schema_types` (JSON Schema definitions) as the catalog's SchemaTypes:
 * `{ kind, description, fields: { name: { type, description, ref } }, values }`.
 * Field type strings follow the YAML schema convention (`number`, `Entity.Seeker[]`,
 * `number[][]`, `A | B`) so lib/catalog.ts reads both.
 */
import type { SchemaField, SchemaType, SchemaTypes } from "../catalog";

type Node = Record<string, unknown>;

const isNode = (v: unknown): v is Node => typeof v === "object" && v !== null && !Array.isArray(v);

const refName = (ref: string) => ref.slice(ref.lastIndexOf("/") + 1);

/** `x-ref` targets anywhere in a property node (through arrays and unions). */
function xRefOf(node: Node): string[] | null {
  const own = node["x-ref"];
  if (Array.isArray(own)) return own.map(String);
  if (typeof own === "string") return [own];
  if (isNode(node.items)) return xRefOf(node.items);
  if (Array.isArray(node.anyOf)) {
    for (const sub of node.anyOf) {
      if (isNode(sub)) {
        const found = xRefOf(sub);
        if (found) return found;
      }
    }
  }
  return null;
}

/** The type string of a property node. */
export function typeString(node: Node): string {
  if (typeof node.$ref === "string") return refName(node.$ref);
  if (Array.isArray(node.anyOf)) {
    const parts = node.anyOf
      .filter(isNode)
      .filter((n) => n.type !== "null")
      .map(typeString);
    return [...new Set(parts)].join(" | ") || "any";
  }
  if (node.type === "array") return `${isNode(node.items) ? typeString(node.items) : "any"}[]`;
  if (Array.isArray(node.enum)) {
    const values = node.enum;
    if (values.every((v) => typeof v === "string")) return "string";
    if (values.every((v) => typeof v === "number")) return "number";
    return "any";
  }
  if (node.type === "integer") return "number";
  if (typeof node.type === "string" && ["string", "number", "boolean"].includes(node.type)) {
    return node.type;
  }
  if (Array.isArray(node.type)) {
    const t = node.type.filter((x) => x !== "null").map(String);
    return t.length === 1 ? (t[0] === "integer" ? "number" : (t[0] ?? "any")) : "any";
  }
  return "any";
}

export function schemaTypeFromDefinition(def: Node): SchemaType {
  const description = typeof def.description === "string" ? def.description : "";
  if (isNode(def.properties)) {
    const fields: Record<string, SchemaField> = {};
    for (const [name, prop] of Object.entries(def.properties)) {
      if (!isNode(prop)) continue;
      const field: SchemaField = { type: typeString(prop) };
      if (typeof prop.description === "string") field.description = prop.description;
      const ref = xRefOf(prop);
      if (ref) field.ref = ref.join(" | ");
      fields[name] = field;
    }
    return { kind: "record", description, fields };
  }
  if (Array.isArray(def.enum)) {
    const xValues = isNode(def["x-values"])
      ? (def["x-values"] as Record<string, string | number>)
      : null;
    const values: Record<string, string | number> = {};
    if (xValues) Object.assign(values, xValues);
    else
      for (const v of def.enum)
        if (typeof v === "string" || typeof v === "number") values[String(v)] = v;
    return { kind: "enum", description, values };
  }
  if (def.type === "array") {
    return {
      kind: "array",
      description,
      arrayOf: isNode(def.items) ? typeString(def.items) : "any",
    };
  }
  return { kind: "other", description };
}

export function schemaTypesFromRows(
  rows: Array<{ name: string; definition: string }>,
): SchemaTypes {
  const out: SchemaTypes = {};
  for (const row of rows) {
    try {
      const def = JSON.parse(row.definition) as unknown;
      if (isNode(def)) out[row.name] = schemaTypeFromDefinition(def);
    } catch {
      // A definition the client cannot read renders as untyped fields.
    }
  }
  return out;
}
