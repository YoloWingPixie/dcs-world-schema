/**
 * The Lua API docs as the database stores them (`api_symbols.entry`, built by
 * tools/package/api_docs.py), plus the hand-written overlays shipped with the site.
 */

/** Where a page lives: a Lua environment's globals, or the mission types. */
export type ApiSection = "mission" | "hooks" | "export" | "server" | "types";

/** Lua environments a member can be tagged with. */
export type ApiEnv = "mission" | "hooks" | "export" | "server";

/** A display token: text, or `{ r }` naming a type (linked through the page's `links`). */
export type Token = string | { r: string };

export type Example = { description?: string; code: string };

export type Param = {
  name: string;
  type: string;
  /** The type as tokens. */
  t: Token[];
  optional?: boolean;
  default?: string;
  description?: string;
};

export type Related = { label: string; href: string };

/** A hand-written overlay (content/api), compiled into public/overlays/api.json. */
export type ApiOverlay = {
  /** Restricts the symbol to one section (else every page or member it names). */
  section?: ApiSection;
  summary?: string;
  description?: string;
  seeAlso?: string[];
  deprecated?: boolean | string;
  since?: string;
  /** Sanitised HTML of the body. */
  html?: string;
  /** Plain text of the body (search). */
  text?: string;
  source: string;
};

export type ApiOverlayFile = { symbols: Record<string, ApiOverlay> };

type Common = {
  description?: string;
  summary?: string;
  addedVersion?: string;
  environment?: ApiEnv[];
  deprecated?: boolean | string;
  examples?: Example[];
  overlay?: ApiOverlay;
};

export type FieldEntry = Common & {
  name: string;
  kind: "function" | "field";
  type?: Token[];
  required?: boolean;
  readonly?: boolean;
  sig?: Token[];
  params?: Param[] | null;
  returns?: Token[][];
  fields?: FieldEntry[];
};

export type Member = Common & {
  kind: "function" | "field" | "constant" | "namespace";
  /** Row name (the member's key). */
  name: string;
  anchor: string;
  qualified: string;
  group: string;
  call?: "." | ":";
  /** null: signature unknown. */
  params?: Param[] | null;
  returns?: Token[][];
  sig?: Token[];
  type?: Token[];
  value?: string | number | boolean;
  readonly?: boolean;
  required?: boolean;
  returnValueExample?: string;
  fields?: FieldEntry[];
  href?: string;
  related?: Related[];
};

export type EnumValue = {
  key: string;
  value: string | number | boolean;
  /** Reference record id the value names (in the page's `valuesSeries`). */
  ref?: string;
};

export type InheritedGroup = {
  from: string;
  href: string;
  members: Array<{ name: string; qualified: string; anchor: string; summary?: string }>;
};

export type PageKind =
  | "class"
  | "singleton"
  | "namespace"
  | "enum"
  | "record"
  | "table"
  | "union"
  | "array";

export type ApiPage = Common & {
  section: ApiSection;
  name: string;
  href: string;
  kind: PageKind;
  groups: Array<{ id: string; title: string; members: Member[] }>;
  parent?: { name: string; href: string };
  inherits?: Array<{ name: string; href?: string }>;
  subclasses?: Array<{ name: string; href: string }>;
  inherited?: InheritedGroup[];
  values?: EnumValue[];
  valuesSeries?: string;
  anyOf?: Token[][];
  arrayOf?: Token[];
  /** Type name (or overlay symbol) -> site path. */
  links: Record<string, string>;
  usedBy: Related[];
};

/** One row of the API home listing. */
export type PageSummary = {
  section: ApiSection;
  name: string;
  href: string;
  kind: PageKind;
  parent: string;
  summary: string;
  count: number;
};
