"""The Lua API documentation as database rows (``tools.package.sqlite``).

From the merged API specs (mission scripting, plus one per other Lua
environment: hooks, export, server) this builds what the reference site renders
its ``/api/...`` pages from, ready to show:

* ``api_symbols``: one row per page (a global, a nested namespace like
  ``trigger.action``, or a type like ``DcsTask.Task.Orbit``) and one per member
  shown on it, in display order. ``section`` is the environment of a global
  (``mission``, ``hooks``, ``export``, ``server``) or ``types`` for the mission
  types; ``page`` the page's path, ``name`` the member (``''`` for the page row
  itself), ``path`` the dotted symbol path (``Unit.getByName``), ``parent`` the
  page a page sits under, ``summary`` the first sentence and ``members`` a
  page's member and value count (listings read these through an index without
  the entries). ``entry`` is JSON: descriptions, params, returns,
  Lua-style signature tokens (``["Unit.getByName(name: string): ", {"r":
  "Unit"}, "?"]``, a ``{"r": name}`` token naming a type), and on page rows
  the member groups, inheritance (``inherits``, ``subclasses``, ``inherited``:
  members declared by an ancestor, with the ancestor's page), enum values
  (``values``, with ``ref``: the reference record id a ``DcsId`` value names
  in ``valuesSeries``) and ``links`` (type name -> site path).
* ``api_type_uses``: the functions taking or returning each type ("used by").
* rows of the ``search`` table with ``series = 'api'``, ``id`` the site path.

Pure: no I/O; rows come out in a deterministic order.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from tools.spec_types import (
    DCS_DB_PREFIX,
    ENTITY_PREFIX,
    Array,
    Literal,
    Map,
    Primitive,
    Ref,
    TypeNode,
    TypeRefError,
    Union,
    parse_type,
)

API_SERIES = "api"  # the ``search.series`` value of API rows
SECTIONS = ("mission", "hooks", "export", "server", "types")
SECTION_LABEL = {
    "mission": "Mission scripting",
    "hooks": "Hooks (GameGUI)",
    "export": "Export",
    "server": "Server",
    "types": "Types",
}
ENV_TAG = {"MissionScripting": "mission", "GameGUI": "hooks", "Server": "server"}
# Sections whose descriptions are generated dump notes: searched by name only.
GENERATED_SECTIONS = frozenset({"hooks", "export", "server"})

# DcsId enums whose values are ids of a reference series (record URLs
# /<series>/<id>/); theatre airbase enums are matched by pattern below.
DCSID_SERIES = {
    "DcsId.AircraftType": "aircraft",
    "DcsId.HelicopterType": "aircraft",
    "DcsId.GroundUnitType": "ground_vehicles",
    "DcsId.ShipType": "ships",
    "DcsId.StructureType": "structures",
    "DcsId.PersonnelType": "personnel",
    "DcsId.WeaponType": "weapons",
    "DcsId.SensorName": "sensors",
    "DcsId.Attribute": "attributes",
    "DcsId.Skill": "skills",
    "DcsId.FormationId": "formations",
}
_THEATRE = re.compile(r"^DcsId\.Theatre\.([^.]+)\.(AirdromeId|AirbaseName)$")
# Enums listed value by value in search (world.event.S_EVENT_SHOT): small, not DcsId.
SEARCH_ENUM_MAX = 200

Json = dict[str, Any]
Token = str | dict[str, str]


def page_href(section: str, name: str) -> str:
    """``/api/Unit/``, ``/api/trigger/action/``, ``/api/types/DcsTask/Task/Orbit/``:
    dots become path segments (a dotted last segment reads as a file name)."""
    path = "/".join(_quote(p) for p in name.split("."))
    return f"/api/{path}/" if section == "mission" else f"/api/{section}/{path}/"


def _quote(segment: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-~]", lambda m: f"%{ord(m.group()):02X}", segment)


def summarize(text: str | None) -> str | None:
    """First sentence, at most ~180 characters."""
    if not text:
        return None
    flat = " ".join(text.split())
    m = re.match(r"^(.+?[.!?])(\s|$)", flat)
    first = m.group(1) if m else flat
    return first if len(first) <= 180 else first[:177].rstrip() + "…"


def name_words(name: str) -> str:
    """``getByName`` -> ``get by name``, ``S_EVENT_SHOT`` -> ``s event shot``."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return " ".join(re.sub(r"[_.:]+", " ", s).lower().split())


# Type tokens -----------------------------------------------------------------


def _is_null(n: TypeNode) -> bool:
    return isinstance(n, Primitive) and n.name in ("nil", "void")


def _emit(n: TypeNode, nested: bool, out: list[Token]) -> None:
    if isinstance(n, Primitive):
        out.append("nil" if n.name == "void" else n.name)
    elif isinstance(n, Ref):
        out.append({"r": n.name})
    elif isinstance(n, Literal):
        out.append(f'"{n.value}"')
    elif isinstance(n, Array):
        if isinstance(n.item, Union):
            out.append("(")
            _emit(n.item, False, out)
            out.append(")[]")
        else:
            _emit(n.item, True, out)
            out.append("[]")
    elif isinstance(n, Map):
        out.append("map<")
        _emit(n.key, False, out)
        out.append(", ")
        _emit(n.value, False, out)
        out.append(">")
    else:
        rest = [m for m in n.members if not _is_null(m)]
        nullable = 0 < len(rest) < len(n.members)
        wrap = nullable and (len(rest) > 1 or nested)
        if wrap:
            out.append("(")
        for i, m in enumerate(rest):
            if i:
                out.append(" | ")
            _emit(m, nullable or nested, out)
        if wrap:
            out.append(")")
        if nullable:
            out.append("?")
        if not rest:
            out.append("nil")


def _merge(tokens: list[Token]) -> list[Token]:
    out: list[Token] = []
    for t in tokens:
        if isinstance(t, str) and out and isinstance(out[-1], str):
            out[-1] += t
        else:
            out.append(t)
    return out


def type_tokens(ref: str) -> list[Token]:
    """A typeRef in Lua style (``T | nil`` is ``T?``), type names as ``{"r": name}``."""
    try:
        node = parse_type(ref)
    except TypeRefError:
        return [ref]
    out: list[Token] = []
    _emit(node, False, out)
    return _merge(out)


def tokens_text(tokens: list[Token]) -> str:
    return "".join(t if isinstance(t, str) else t["r"] for t in tokens)


def signature_tokens(
    qualified: str, params: list[Json] | None, returns: list[str]
) -> list[Token]:
    """``Unit.getByName(name: string): Unit?``; ``(...)`` when unknown."""
    out: list[Token] = [qualified]
    if params is None:
        return [f"{qualified}(...)"]
    out.append("(")
    for i, p in enumerate(params):
        if i:
            out.append(", ")
        out.append(f"{p['name']}{'?' if p.get('optional') else ''}: ")
        out.extend(type_tokens(p["type"]))
    out.append(")")
    shown = [r for r in returns if r != "void"]
    if shown:
        out.append(": ")
        for i, r in enumerate(shown):
            if i:
                out.append(", ")
            out.extend(type_tokens(r))
    return _merge(out)


def _ref_names(tokens: list[Token]) -> list[str]:
    return [t["r"] for t in tokens if isinstance(t, dict)]


# Model -----------------------------------------------------------------------


@dataclass
class Member:
    kind: str  # function | field | constant | namespace
    name: str
    anchor: str
    qualified: str
    group: str = ""
    data: Json = field(default_factory=dict)
    type_refs: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)


@dataclass
class Page:
    section: str
    name: str
    kind: str
    data: Json = field(default_factory=dict)
    groups: list[tuple[str, str]] = field(default_factory=list)
    members: list[Member] = field(default_factory=list)
    inherits: list[str] = field(default_factory=list)
    parent: str = ""
    refs: list[str] = field(default_factory=list)

    @property
    def href(self) -> str:
        return page_href(self.section, self.name)


def _env_list(v: Any) -> list[str] | None:
    if not isinstance(v, list) or "All" in v:
        return None
    out = list(dict.fromkeys(ENV_TAG[x] for x in v if x in ENV_TAG))
    return out or None


def _examples(v: Any) -> list[Json] | None:
    if not isinstance(v, list):
        return None
    out = []
    for e in v:
        if isinstance(e, dict) and str(e.get("code", "")).strip():
            ex: Json = {"code": str(e["code"]).rstrip()}
            if isinstance(e.get("description"), str) and e["description"].strip():
                ex["description"] = e["description"].strip()
            out.append(ex)
    return out or None


def _common(data: Json, d: Json) -> None:
    desc = d.get("description")
    if isinstance(desc, str) and desc.strip():
        data["description"] = desc.strip()
        data["summary"] = summarize(desc)
    if isinstance(d.get("addedVersion"), str):
        data["addedVersion"] = d["addedVersion"]
    if env := _env_list(d.get("environment")):
        data["environment"] = env
    if d.get("deprecated") is True:
        data["deprecated"] = True
    if ex := _examples(d.get("examples")):
        data["examples"] = ex


def _anchor(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name) or "_"


def _sort_key(name: str) -> tuple[str, str]:
    return (name.lower(), name)


def _member(
    name: str, d: Json, owner: str, call: str, required: bool | None = None
) -> Member:
    is_fn = "returns" in d or "params" in d
    unknown_fn = not is_fn and d.get("type") == "function"
    fn = is_fn or unknown_fn
    m = Member(
        kind="function" if fn else "field",
        name=name,
        anchor=_anchor(name),
        qualified=f"{owner}{call if fn else '.'}{name}",
    )
    data = m.data
    if is_fn:
        params = []
        for p in d.get("params") or []:
            if not isinstance(p, dict):
                continue
            param: Json = {"name": str(p["name"]), "type": str(p.get("type", "any"))}
            if p.get("optional") is True:
                param["optional"] = True
            if "default" in p:
                param["default"] = json.dumps(p["default"], ensure_ascii=False)
            if isinstance(p.get("description"), str) and p["description"].strip():
                param["description"] = p["description"].strip()
                m.texts.append(param["description"])
            param["t"] = type_tokens(param["type"])
            m.type_refs.append(param["type"])
            params.append(param)
        r = d.get("returns")
        returns = (
            [str(x) for x in r]
            if isinstance(r, list)
            else [r]
            if isinstance(r, str)
            else ["void"]
        )
        data["call"] = call
        data["params"] = params
        data["returns"] = [type_tokens(x) for x in returns if x != "void"]
        data["sig"] = signature_tokens(m.qualified, params, returns)
        m.type_refs.extend(returns)
        if isinstance(d.get("returnValueExample"), str):
            data["returnValueExample"] = d["returnValueExample"]
    elif unknown_fn:
        data["call"] = call
        data["params"] = None
        data["sig"] = signature_tokens(m.qualified, None, [])
    else:
        t = "table" if d.get("kind") == "table" else str(d.get("type", "any"))
        data["type"] = type_tokens(t)
        m.type_refs.append(t)
        if d.get("readonly") is True:
            data["readonly"] = True
        if required is not None:
            data["required"] = required
        if isinstance(d.get("fields"), dict):
            req = set(d.get("required") or [])
            subs = [
                _member(n, sd, f"{owner}.{name}", ".", n in req)
                for n, sd in d["fields"].items()
                if isinstance(sd, dict)
            ]
            subs.sort(key=lambda x: _sort_key(x.name))
            data["fields"] = [{"name": s.name, **s.data} for s in subs]
            for s in subs:
                m.type_refs.extend(s.type_refs)
                m.texts.extend(s.texts)
    _common(data, d)
    if "description" in data:
        m.texts.append(data["description"])
    return m


def _members(mapping: Any, owner: str, call: str) -> list[Member]:
    if not isinstance(mapping, dict):
        return []
    out = [
        _member(n, d, owner, call) for n, d in mapping.items() if isinstance(d, dict)
    ]
    return sorted(out, key=lambda m: _sort_key(m.name))


def _add_group(page: Page, gid: str, title: str, members: list[Member]) -> None:
    if not members:
        return
    taken = {m.anchor.lower() for m in page.members}
    for m in members:
        anchor, n = m.anchor, 2
        while anchor.lower() in taken:
            anchor, n = f"{m.anchor}-{n}", n + 1
        m.anchor = anchor
        taken.add(anchor.lower())
        m.group = gid
    page.groups.append((gid, title))
    page.members.extend(members)


def _split(ms: list[Member]) -> tuple[list[Member], list[Member]]:
    return [m for m in ms if m.kind == "function"], [
        m for m in ms if m.kind != "function"
    ]


def _new_page(section: str, name: str, kind: str, d: Json) -> Page:
    p = Page(section, name, kind)
    _common(p.data, d)
    return p


def _global_pages(section: str, globals_: dict[str, Any]) -> list[Page]:
    out: list[Page] = []
    for name, d in globals_.items():
        if not isinstance(d, dict):
            continue
        kind = str(d.get("kind"))
        page = _new_page(section, name, kind, d)
        page.inherits = [str(x) for x in d.get("inherits") or []]
        statics = _split(_members(d.get("static"), name, "."))
        inst = _split(_members(d.get("instance"), name, ":"))
        props: list[Member] = []
        namespaces: list[Member] = []
        required = set(d.get("required") or [])
        for pname, pd in (d.get("properties") or {}).items():
            if not isinstance(pd, dict):
                continue
            if isinstance(pd.get("static"), dict) or isinstance(
                pd.get("instance"), dict
            ):
                ns_name = f"{name}.{pname}"
                ns = _new_page(section, ns_name, "namespace", pd)
                ns.parent = name
                fns, fields = _split(_members(pd.get("static"), ns_name, "."))
                _add_group(ns, "functions", "Functions", fns)
                _add_group(ns, "fields", "Fields", fields)
                _add_group(
                    ns, "methods", "Methods", _members(pd.get("instance"), ns_name, ":")
                )
                out.append(ns)
                m = Member("namespace", pname, _anchor(pname), ns_name)
                _common(m.data, pd)
                m.data["href"] = ns.href
                namespaces.append(m)
            else:
                props.append(
                    _member(
                        pname, pd, name, ".", (pname in required) if required else None
                    )
                )
        constants = [
            Member("constant", k, _anchor(k), f"{name}.{k}", data={"value": v})
            for k, v in (d.get("constants") or {}).items()
        ]
        constants.sort(key=lambda m: _sort_key(m.name))
        if kind == "class":
            _add_group(page, "static-functions", "Static functions", statics[0])
            _add_group(page, "static-fields", "Static fields", statics[1])
            _add_group(page, "methods", "Methods", inst[0])
            _add_group(page, "fields", "Fields", inst[1])
        else:
            _add_group(
                page,
                "functions",
                "Functions",
                sorted(statics[0] + inst[0], key=lambda m: _sort_key(m.name)),
            )
            _add_group(
                page,
                "fields",
                "Fields",
                sorted(statics[1] + inst[1], key=lambda m: _sort_key(m.name)),
            )
        _add_group(
            page,
            "namespaces",
            "Namespaces",
            sorted(namespaces, key=lambda m: _sort_key(m.name)),
        )
        _add_group(
            page,
            "properties",
            "Properties",
            sorted(props, key=lambda m: _sort_key(m.name)),
        )
        _add_group(page, "constants", "Constants", constants)
        if isinstance(d.get("arrayOf"), str):
            page.data["arrayOf"] = type_tokens(f"{d['arrayOf']}[]")
            page.refs.append(d["arrayOf"])
        out.append(page)
    return out


def _value_ref(
    name: str, values: dict[str, Any], types: dict[str, Any]
) -> tuple[str, Any] | None:
    """``(series, record id of a value)`` for an enum naming reference records."""
    if name in DCSID_SERIES:
        series = DCSID_SERIES[name]
        if series == "formations":
            return series, lambda k, v: k
        return series, lambda k, v: str(v)
    m = _THEATRE.match(name)
    if not m:
        return None
    theatre, which = m.groups()
    if which == "AirdromeId":
        return "airbases", lambda k, v: f"{theatre}.{v}"
    ids = (types.get(f"DcsId.Theatre.{theatre}.AirdromeId") or {}).get("values") or {}
    return "airbases", lambda k, v: f"{theatre}.{ids[v]}" if v in ids else None


def _type_pages(types: dict[str, Any]) -> list[Page]:
    out: list[Page] = []
    for name, d in types.items():
        if not isinstance(d, dict):
            continue
        kind = str(d.get("kind"))
        page = _new_page("types", name, kind, d)
        if kind == "enum" and isinstance(d.get("values"), dict):
            linker = _value_ref(name, d["values"], types)
            values = []
            for k, v in d["values"].items():
                row: Json = {"key": k, "value": v}
                if linker and (rid := linker[1](k, v)) is not None:
                    row["ref"] = rid
                values.append(row)
            page.data["values"] = values
            if linker:
                page.data["valuesSeries"] = linker[0]
        if isinstance(d.get("fields"), dict):
            req = set(d.get("required") or [])
            has_req = isinstance(d.get("required"), list)
            fields = [
                _member(n, fd, name, ".", (n in req) if has_req else None)
                for n, fd in d["fields"].items()
                if isinstance(fd, dict)
            ]
            _add_group(
                page, "fields", "Fields", fields
            )  # schema order (id before params)
        if isinstance(d.get("anyOf"), list):
            page.data["anyOf"] = [type_tokens(str(t)) for t in d["anyOf"]]
            page.refs.extend(str(t) for t in d["anyOf"])
        if isinstance(d.get("arrayOf"), str):
            page.data["arrayOf"] = type_tokens(f"{d['arrayOf']}[]")
            page.refs.append(d["arrayOf"])
        out.append(page)
    return out


@dataclass
class ApiRows:
    symbols: list[tuple[Any, ...]]  # api_symbols rows
    uses: list[tuple[str, str, str, str]]  # api_type_uses rows
    search: list[tuple[str, str, str, str, str]]  # search rows (series 'api')
    counts: dict[str, int]


def _api_types(spec: Json) -> dict[str, Any]:
    return {
        n: t
        for n, t in (spec.get("types") or {}).items()
        if not n.startswith((ENTITY_PREFIX, DCS_DB_PREFIX))
    }


def build_rows(mission: Json, envs: dict[str, Json]) -> ApiRows:
    """Rows of the API tables from the merged mission spec and the env specs."""
    types = _api_types(mission)
    pages = _global_pages("mission", mission.get("globals") or {})
    for env in ("hooks", "export", "server"):
        if env in envs:
            pages += _global_pages(env, envs[env].get("globals") or {})
    pages += _type_pages(types)
    index = {(p.section, p.name): p for p in pages}

    def find(section: str, name: str) -> Page | None:
        env = "mission" if section == "types" else section
        return (
            index.get(("types", name))
            or index.get((env, name))
            or (index.get(("mission", name)) if env != "mission" else None)
        )

    def resolve(section: str, name: str) -> str | None:
        if page := find(section, name):
            return page.href
        owner, _, member = name.rpartition(".")
        env = "mission" if section == "types" else section
        if owner and (p := index.get((env, owner))):
            for m in p.members:
                if m.name == member:
                    return m.data.get("href") or f"{p.href}#{m.anchor}"
        return None

    # Inheritance: nearest declaring ancestor wins; own members shadow.
    subclasses: dict[tuple[str, str], list[Page]] = {}
    for page in pages:
        if not page.inherits:
            continue

        def anc_of(name: str, section: str = page.section) -> Page | None:
            return index.get((section, name)) or index.get(("types", name))

        page.data["inherits"] = [
            {"name": n, **({"href": a.href} if (a := anc_of(n)) else {})}
            for n in page.inherits
        ]
        seen = {m.name for m in page.members}
        visited = {page.name}
        queue = list(page.inherits)
        inherited = []
        while queue:
            name = queue.pop(0)
            if name in visited:
                continue
            visited.add(name)
            anc = anc_of(name)
            if not anc:
                continue
            items = []
            for m in anc.members:
                if m.kind == "namespace" or m.name in seen:
                    continue
                seen.add(m.name)
                call = (
                    "."
                    if m.kind != "function"
                    else ":"
                    if anc.section == "types"
                    else m.data.get("call", ".")
                )
                item: Json = {
                    "name": m.name,
                    "qualified": f"{page.name}{call}{m.name}",
                    "anchor": m.anchor,
                }
                if m.data.get("summary"):
                    item["summary"] = m.data["summary"]
                items.append(item)
            if items:
                inherited.append({"from": anc.name, "href": anc.href, "members": items})
            queue.extend(anc.inherits)
            subclasses.setdefault((anc.section, anc.name), []).append(page)
        if inherited:
            page.data["inherited"] = inherited
    for key, subs in subclasses.items():
        index[key].data["subclasses"] = [
            {"name": s.name, "href": s.href}
            for s in sorted(subs, key=lambda s: _sort_key(s.name))
        ]

    # Links, used-by, get/set pairs.
    uses: dict[tuple[str, str, str], str] = {}
    for page in pages:
        names: list[str] = []
        for m in page.members:
            _add_names(names, m.type_refs)
            if m.kind == "function":
                for r in m.type_refs:
                    for n in _ref_names(type_tokens(r)):
                        target = find(page.section, n)
                        if target:
                            uses[(target.section, target.name, m.qualified)] = (
                                f"{page.href}#{m.anchor}"
                            )
        by_group: dict[str, dict[str, Member]] = {}
        for m in page.members:
            if m.kind == "function":
                by_group.setdefault(m.group, {})[m.name] = m
        for fns in by_group.values():
            for m in fns.values():
                stem = m.name[3:] if m.name.startswith("get") else None
                other = fns.get(f"set{stem}") if stem else None
                if other:
                    m.data["related"] = [
                        {
                            "label": other.qualified,
                            "href": f"{page.href}#{other.anchor}",
                        }
                    ]
                    other.data["related"] = [
                        {"label": m.qualified, "href": f"{page.href}#{m.anchor}"}
                    ]
        _add_names(names, page.refs)
        names.extend(n for n in page.inherits if n not in names)
        texts = [page.data.get("description", "")] + [
            t for m in page.members for t in m.texts
        ]
        for t in texts:
            for n in re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*)`", t or ""):
                if n not in names and n != page.name:
                    names.append(n)
        links = {}
        for n in names:
            if href := resolve(page.section, n):
                links[n] = href
        page.data["links"] = links

    # Rows ----------------------------------------------------------------
    symbols: list[tuple[Any, ...]] = []
    search: list[tuple[str, str, str, str, str]] = []
    order = {s: i for i, s in enumerate(SECTIONS)}

    def search_row(
        href: str,
        path: str,
        kind: str,
        section: str,
        summary: str,
        text: str,
        name: str,
    ) -> None:
        meta = f"{kind} · {SECTION_LABEL[section]}"
        subtitle = f"{meta} · {summary}" if summary else meta
        keywords = " ".join(
            dict.fromkeys(filter(None, [name_words(name), name_words(path), text]))
        )
        search.append((API_SERIES, href, path, subtitle, keywords))

    for page in sorted(pages, key=lambda p: (order[p.section], p.name)):
        generated = page.section in GENERATED_SECTIONS
        entry = {
            "kind": page.kind,
            **page.data,
            "groups": [{"id": g, "title": t} for g, t in page.groups],
        }
        if page.parent:
            entry["parent"] = {
                "name": page.parent,
                "href": page_href(page.section, page.parent),
            }
        symbols.append(
            (
                page.section,
                page.name,
                "",
                page.name,
                page.kind,
                page.parent,
                page.data.get("summary") or "",
                len(page.members) + len(page.data.get("values") or []),
                _json(entry),
            )
        )
        search_row(
            page.href,
            page.name,
            "global" if page.kind == "singleton" else page.kind,
            page.section,
            page.data.get("summary") or "",
            "" if generated else page.data.get("description", ""),
            page.name.split(".")[-1],
        )
        for m in page.members:
            mkind = (
                "method"
                if m.kind == "function" and m.data.get("call") == ":"
                else m.kind
            )
            entry = {
                "kind": m.kind,
                "anchor": m.anchor,
                "qualified": m.qualified,
                "group": m.group,
                **m.data,
            }
            path = m.qualified.replace(":", ".")
            symbols.append(
                (
                    page.section,
                    page.name,
                    m.name,
                    path,
                    mkind,
                    page.name,
                    m.data.get("summary") or "",
                    0,
                    _json(entry),
                )
            )
            if m.kind == "namespace" or page.section == "types":
                continue  # namespaces have their page; record fields are found via their type
            summary = (m.data.get("summary") or "") if not generated else ""
            if not summary and "value" in m.data:
                summary = f"= {json.dumps(m.data['value'], ensure_ascii=False)}"
            search_row(
                f"{page.href}#{m.anchor}",
                m.qualified,
                mkind,
                page.section,
                summary,
                "" if generated else " ".join(m.texts),
                m.name,
            )
        values = page.data.get("values")
        if (
            values
            and not page.name.startswith("DcsId.")
            and len(values) <= SEARCH_ENUM_MAX
        ):
            for v in values:
                search_row(
                    f"{page.href}#v-{_quote(str(v['key']))}",
                    f"{page.name}.{v['key']}",
                    "constant",
                    page.section,
                    f"= {json.dumps(v['value'], ensure_ascii=False)}",
                    "",
                    str(v["key"]),
                )

    use_rows = sorted(
        (section, name, label, href) for (section, name, label), href in uses.items()
    )
    counts = {
        "pages": len(pages),
        "classes": sum(p.kind == "class" for p in pages),
        "globals": sum(
            p.section != "types" and p.kind in ("singleton", "namespace") for p in pages
        ),
        "types": sum(p.section == "types" for p in pages),
        "enums": sum(p.kind == "enum" for p in pages),
        "functions": sum(m.kind == "function" for p in pages for m in p.members),
    }
    return ApiRows(symbols, use_rows, sorted(search), counts)


def _add_names(names: list[str], refs: list[str]) -> None:
    """Append the type names ``refs`` mention to ``names`` (once each)."""
    for r in refs:
        for n in _ref_names(type_tokens(r)):
            if n not in names:
                names.append(n)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
