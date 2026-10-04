import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parse } from "yaml";
import type { SchemaTypes } from "../../src/lib/catalog";

/** Every type of every dcs-world-schema/types/entities/*.yaml, merged. */
export function loadSchemaTypes(schemaDir: string): SchemaTypes {
  const types: SchemaTypes = {};
  for (const file of readdirSync(schemaDir)
    .filter((f) => f.endsWith(".yaml"))
    .sort()) {
    const doc = parse(readFileSync(join(schemaDir, file), "utf8")) as { types?: SchemaTypes };
    Object.assign(types, doc.types ?? {});
  }
  return types;
}
