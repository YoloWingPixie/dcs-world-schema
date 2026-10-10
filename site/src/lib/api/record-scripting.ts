/**
 * A record page's Scripting rows (lib/api/scripting.ts): the Lua class, the member and enum
 * values naming the record, each kept only when the API data confirms it. Record pages
 * import this lazily, after the record has rendered.
 */
import type { Query } from "../db/reference";
import { apiHref } from "./routes";
import { enumMemberText, enumValueHash, namesKey, SCRIPTING } from "./scripting";
import type { EnumValue, Member } from "./types";

type Json = Record<string, unknown>;

/** Text, linked when `href` is set; `code` sets it in mono. */
export type ScriptingText = { text: string; href?: string; code?: boolean };

export type ScriptingRow = {
  /** Stable key (and test hook). */
  id: string;
  label: ScriptingText;
  /** Muted after the label: what the member does with the value (`returns`). */
  verb?: string;
  value: ScriptingText;
  /** A second line under the value. */
  note?: string;
};

/**
 * Classes and members by path (`Unit`, `Unit.getTypeName`): their pages and, for members,
 * the call as Lua writes it (`Unit:getTypeName()`, methods with `:`). Missing ones are left out.
 */
async function symbols(q: Query, paths: string[]) {
  const out = new Map<string, { href: string; call: string }>();
  if (!paths.length) return out;
  const rows = await q(
    `SELECT page, name, path, entry FROM api_symbols
      WHERE section = 'mission' AND path IN (${paths.map(() => "?").join(",")})`,
    paths,
  );
  for (const r of rows) {
    const base = apiHref("mission", String(r.page));
    if (r.name === "") {
      out.set(String(r.path), { href: base, call: String(r.page) });
      continue;
    }
    const m = JSON.parse(String(r.entry)) as Member;
    out.set(String(r.path), {
      href: m.href ?? `${base}#${m.anchor}`,
      call: `${m.qualified ?? r.path}()`,
    });
  }
  return out;
}

/** Enum pages' values and `valuesSeries` (head rows only). */
async function enumPages(q: Query, pages: string[]) {
  const out = new Map<string, { values: EnumValue[]; series?: string }>();
  if (!pages.length) return out;
  const rows = await q(
    `SELECT page, entry FROM api_symbols
      WHERE section = 'types' AND name = '' AND page IN (${pages.map(() => "?").join(",")})`,
    pages,
  );
  for (const r of rows) {
    const e = JSON.parse(String(r.entry)) as {
      kind?: string;
      values?: EnumValue[];
      valuesSeries?: string;
    };
    if (e.kind !== "enum" || !e.values) continue;
    out.set(String(r.page), {
      values: e.values,
      ...(e.valuesSeries ? { series: e.valuesSeries } : {}),
    });
  }
  return out;
}

const literal = (v: unknown) => (typeof v === "string" ? JSON.stringify(v) : String(v));

const enumLink = (page: string, key: string): ScriptingText => ({
  text: enumMemberText(page, key),
  href: `${apiHref("types", page)}${enumValueHash(key)}`,
  code: true,
});

export async function loadScripting(
  q: Query,
  series: string,
  id: string,
  data: Json,
): Promise<ScriptingRow[]> {
  const spec = SCRIPTING[series];
  if (!spec) return [];
  const theatre = typeof data.theatre === "string" ? data.theatre : "";
  const enumNames = spec.enums
    .map((e) => (e.includes("{theatre}") ? (theatre ? e.replace("{theatre}", theatre) : "") : e))
    .filter(Boolean);
  const valueEnums = (spec.values ?? []).flatMap((v) => v.enums);
  const members = [
    ...(spec.member ? [spec.member] : []),
    ...(spec.fields ?? []).map((f) => f.member),
    ...(spec.attributes ? ["Object.hasAttribute"] : []),
  ];
  const [calls, enums] = await Promise.all([
    symbols(q, [...(spec.class ? [spec.class] : []), ...members]),
    enumPages(q, [...enumNames, ...valueEnums, ...(spec.attributes ? ["DcsId.Attribute"] : [])]),
  ]);

  const rows: ScriptingRow[] = [];
  const cls = spec.class ? calls.get(spec.class) : undefined;
  if (spec.class && cls) {
    rows.push({
      id: "class",
      label: { text: "Lua class" },
      value: { text: spec.class, href: cls.href, code: true },
    });
  }

  // The record in its enums (the enum must list this series' records and this one).
  const listed = enumNames.flatMap((page) => {
    const e = enums.get(page);
    const v = e?.series === series ? e.values.find((x) => x.ref === id) : undefined;
    return e && v ? [{ page, value: v }] : [];
  });
  const member = spec.member ? calls.get(spec.member) : undefined;
  const first = listed[0];
  if (member && first) {
    rows.push({
      id: "member",
      label: { text: member.call, href: member.href, code: true },
      verb: spec.memberRole === "takes" ? "takes" : "returns",
      value: { text: literal(first.value.value), code: true },
    });
  }
  for (const f of spec.fields ?? []) {
    const call = calls.get(f.member);
    const v = data[f.path];
    if (!call || (typeof v !== "string" && typeof v !== "number")) continue;
    rows.push({
      id: `field-${f.path}`,
      label: { text: call.call, href: call.href, code: true },
      verb: "returns",
      value: { text: literal(v), code: true },
    });
  }
  for (const v of spec.values ?? []) {
    const raw = data[v.path];
    const name = data[v.name];
    if (typeof raw !== "number" || typeof name !== "string") continue;
    for (const page of v.enums) {
      const hit = enums.get(page)?.values.find((x) => x.value === raw && namesKey(name, x.key));
      if (!hit) continue;
      rows.push({
        id: `value-${v.path}`,
        label: { text: v.path === "type" ? "Type" : "Category" },
        value: enumLink(page, hit.key),
        note: `${name} = ${raw}`,
      });
      break;
    }
  }
  for (const { page, value } of listed) {
    rows.push({
      id: `enum-${page}`,
      label: { text: "Listed in" },
      value: enumLink(page, value.key),
      // The value, when the key is not it and no member row above already gives it.
      ...(value.key !== String(value.value) && !(member && value === first?.value)
        ? { note: `= ${literal(value.value)}` }
        : {}),
    });
  }
  const attrs = Array.isArray(data.attributes) ? data.attributes.length : 0;
  const has = calls.get("Object.hasAttribute");
  if (spec.attributes && has && attrs && enums.has("DcsId.Attribute")) {
    rows.push({
      id: "attributes",
      label: { text: has.call, href: has.href, code: true },
      value: { text: "DcsId.Attribute", href: apiHref("types", "DcsId.Attribute"), code: true },
      note: `true for this type's ${attrs} ${attrs === 1 ? "attribute" : "attributes"}`,
    });
  }
  return rows;
}
