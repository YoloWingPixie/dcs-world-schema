import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.datamine.api_dump import scalars_at
from tools.spec_types import (
    Literal,
    Primitive,
    Ref,
    TypeNode,
    format_type,
    members,
    parse_type,
)

IGNORED_METHODS = {
    "__eq",
    "__index",
    "__le",
    "__lt",
    "__newindex",
    "__tonumber",
    "tonumber",
    "parentClass_",
    "className_",
    "database_",
}


def add_member(s: dict[str, set[str]], ns: str, m: str) -> None:
    s.setdefault(ns, set()).add(m)


def enum_literals(
    node: dict[str, Any], ns: str, s: dict[str, set[str]], pref: str
) -> None:
    if node.get("kind") == "enum" and "values" in node:
        for v in node["values"]:
            add_member(s, ns, f"{pref}.{v}")


def walk_table(
    t: dict[str, Any], ns: str, s: dict[str, set[str]], pref: str = ""
) -> None:
    for sec in ("instance", "static", "properties"):
        if sec not in t or not isinstance(t[sec], dict):
            continue
        for n, sub in t[sec].items():
            if n in IGNORED_METHODS:
                continue
            p = f"{pref}.{n}" if pref else n
            add_member(s, ns, p)
            if isinstance(sub, dict):
                enum_literals(sub, ns, s, p)
                walk_table(sub, ns, s, p)
    enum_literals(t, ns, s, pref)


def harvest_parent(item: dict[str, Any]) -> str | None:
    if "value" in item and isinstance(item["value"], str):
        return item["value"].strip()
    if "sub" in item and isinstance(item["sub"], dict):
        for sub in item["sub"].get("members", []):
            if sub.get("name") == "className_" and "value" in sub:
                value: str = sub["value"]
                return value.strip()
    return None


def process_members(
    members: list[dict[str, Any]], ns: str, s: dict[str, set[str]], pref: str = ""
) -> None:
    for mem in members:
        if not isinstance(mem, dict):
            continue
        n = mem.get("name")
        if not n or n in IGNORED_METHODS:
            continue
        fp = f"{pref}.{n}" if pref else n
        add_member(s, ns, fp)
        enum_literals(mem, ns, s, fp)
        if "sub" in mem and isinstance(mem["sub"], dict):
            process_members(mem["sub"].get("members", []), ns, s, fp)


def build_parent_map(raw: dict[str, Any]) -> dict[str, str]:
    pm: dict[str, str] = {}
    for cls, cdef in raw.items():
        if not isinstance(cdef, dict) or "members" not in cdef:
            continue
        for it in cdef["members"]:
            if it.get("name") == "parentClass_":
                p = harvest_parent(it)
                if p and p != "void":
                    pm[cls] = p
                break
    return pm


def inherit(s: dict[str, set[str]], pm: dict[str, str]) -> None:
    memo: dict[str, set[str]] = {}

    def anc(c: str) -> set[str]:
        if c in memo:
            return memo[c]
        if c not in pm:
            memo[c] = {c}
            return memo[c]
        memo[c] = {c} | anc(pm[c])
        return memo[c]

    for ch in list(s):
        for a in anc(ch) - {ch}:
            if a in s:
                s[ch].update(s[a])


def extract_dcs(api: dict[str, Any], ignore_env: bool = True) -> dict[str, set[str]]:
    s: dict[str, set[str]] = {}
    for ns, nsd in api.items():
        if ignore_env and ns == "env":
            continue
        if isinstance(nsd, dict) and isinstance(nsd.get("members"), list):
            s[ns] = set()
            process_members(nsd["members"], ns, s)
    pm = build_parent_map(api)
    inherit(s, pm)
    if "env" in s:
        s["env"].difference_update({"warehouses", "mission"})
    return s


def extract_schema(schema: dict[str, Any], api: dict[str, Any]) -> dict[str, set[str]]:
    s: dict[str, set[str]] = {}
    api_struct = extract_dcs(api, ignore_env=False)
    canon = {f"{n}.{m}".lower(): f"{n}.{m}" for n, ms in api_struct.items() for m in ms}

    def add(ns: str, m: str) -> None:
        k = f"{ns}.{m}".lower()
        c = canon.get(k, f"{ns}.{m}")
        rel = c[len(ns) + 1 :] if c.lower().startswith(f"{ns.lower()}.") else m
        add_member(s, ns, rel)

    for ns, nd in schema.get("globals", {}).items():
        walk_table(nd, ns, s)
    for fn, td in schema.get("types", {}).items():
        if "." not in fn:
            continue
        ns, rel = fn.split(".", 1)
        add(ns, rel)
        walk_table(td, ns, s, rel)
    pm = build_parent_map(api)
    inherit(s, pm)
    return s


def compare(schema_s: dict[str, set[str]], dcs_s: dict[str, set[str]]) -> bool:
    sn, dn = set(schema_s), set(dcs_s)
    missing_namespace = False
    missing_members = False

    for ns in sorted(dn - sn):
        print(f"Namespace missing in schema: {ns}")
        missing_namespace = True

    for ns in sorted(sn - dn):
        print(f"Extra namespace in schema: {ns}")
        # Extra namespaces are warnings, not errors

    for ns in sorted(sn & dn):
        miss = dcs_s[ns] - schema_s[ns]
        extra = schema_s[ns] - dcs_s[ns]
        if miss or extra:
            print(f"\nNamespace: {ns}")
            if miss:
                print("  Missing members:")
                for m in sorted(miss):
                    print(f"    - {m}")
                missing_members = True
            if extra:
                print("  Extra members:")
                for m in sorted(extra):
                    print(f"    - {m}")
        else:
            print(f"Namespace OK: {ns}")

    # Return True if there are missing namespaces or members
    return missing_namespace or missing_members


def enum_value_drift(schema: dict[str, Any], api: dict[str, Any]) -> list[str]:
    """Where a schema enum named for a dump table (``AI.Skill``) has a value
    other than the dump's for the same key."""
    out: list[str] = []
    for name, td in sorted(schema.get("types", {}).items()):
        if "." not in name or td.get("kind") != "enum":
            continue
        dcs = scalars_at(api, name)
        if dcs is None:
            continue
        for key, value in (td.get("values") or {}).items():
            if key in dcs and dcs[key] != value:
                out.append(f"{name}.{key}: schema {value!r}, DCS {dcs[key]!r}")
    return out


def load_api(paths: list[str]) -> dict[str, Any]:
    """The first existing of ``paths``, a scripting env file of the API dump
    hook (``api/scripting.json``), mapped to the legacy shape."""
    from tools.datamine.api_dump import legacy

    for path in paths:
        if Path(path).is_file():
            print(f"API dump: {path}")
            with Path(path).open(encoding="utf-8") as f:
                api = json.load(f)
            if not str(api.get("format", "")).startswith("dcs-api-dump/"):
                print(f"{path} is not a dcs-api-dump file")
                sys.exit(1)
            return legacy(api)
    print(f"No API dump found: {', '.join(paths)}")
    sys.exit(1)


PRIMITIVES = {
    "any", "boolean", "function", "integer", "nil", "number", "string",
    "table", "userdata", "void",
}  # fmt: skip
UNDOCUMENTED = "signature not documented"


def _lua_kind(node: TypeNode) -> str:
    """A union member as a Lua type name (a literal: ``string``) or its typeRef."""
    if isinstance(node, Literal):
        return "string"
    return node.name if isinstance(node, Primitive | Ref) else format_type(node)


def _compatible(probed: str, documented: str) -> bool:
    """Loosely: the documented type (a union) admits the probed Lua type; a
    named type (class, record, enum, array) admits any."""
    parts = {_lua_kind(m) for m in members(parse_type(documented))}
    if probed in parts or "any" in parts or parts - PRIMITIVES:
        return True
    return probed == "number" and "integer" in parts


def _schema_member(
    schema: dict[str, Any], path: str
) -> tuple[dict[str, Any] | None, bool]:
    """The member at a probe path (``Global.a.b``) in the merged schema, a
    class's through its inherited classes, and whether it is an instance
    member."""
    globals_ = schema.get("globals", {})
    name, *rest = path.split(".")
    if not rest:
        return None, False

    def find(
        node: dict[str, Any], keys: list[str], seen: frozenset[str]
    ) -> tuple[dict[str, Any] | None, bool]:
        key, *more = keys
        for section in ("instance", "static", "properties"):
            sub = (node.get(section) or {}).get(key)
            if isinstance(sub, dict):
                if not more:
                    return sub, section == "instance"
                found = find(sub, more, seen)
                if found[0] is not None:
                    return found
        for parent in node.get("inherits") or []:
            if parent not in seen and isinstance(globals_.get(parent), dict):
                found = find(globals_[parent], keys, seen | {parent})
                if found[0] is not None:
                    return found
        return None, False

    node = globals_.get(name)
    return (
        find(node, rest, frozenset({name})) if isinstance(node, dict) else (None, False)
    )


def probe_disagreements(schema: dict[str, Any], probe: dict[str, Any]) -> list[str]:
    """Where a conclusive probe record of the scripting env disagrees with the
    documented signature: required argument count, argument types, returns."""
    out: list[str] = []
    for path, rec in sorted((probe.get("envs", {}).get("scripting") or {}).items()):
        if not rec.get("conclusive"):
            continue
        member, instance = _schema_member(schema, path)
        if not member or "returns" not in member:
            continue
        if UNDOCUMENTED in str(member.get("description") or ""):
            continue
        params = [q for q in rec.get("params") or [] if q.get("from") != "self"]
        offset = 1 if len(params) < len(rec.get("params") or []) else 0
        probed_n = (rec.get("minArgs") or 0) - offset
        doc_params = member.get("params") or []
        doc_n = sum(not p.get("optional") for p in doc_params)
        issues = []
        if probed_n != doc_n:
            issues.append(
                f"DCS needed {probed_n} argument(s), documented requires {doc_n}"
            )
        for q in params:
            i = q["position"] - 1 - offset
            if i < len(doc_params) and not _compatible(
                q["expected"], str(doc_params[i].get("type", "any"))
            ):
                issues.append(
                    f"argument {i + 1} ({doc_params[i].get('name')}): DCS expects "
                    f"{q['expected']}, documented {doc_params[i].get('type')}"
                )
        doc_returns = member["returns"]
        if not isinstance(doc_returns, list):
            doc_returns = [] if doc_returns in ("void", "nil") else [doc_returns]
        observed = rec.get("returns") or []
        if len(observed) > len(doc_returns):
            issues.append(
                f"returned {len(observed)} value(s), documented {len(doc_returns)}"
            )
        for i, r in enumerate(observed[: len(doc_returns)]):
            t = r.get("className") or r.get("type")
            if r.get("type") != "nil" and not _compatible(
                r.get("type"), str(doc_returns[i])
            ):
                issues.append(
                    f"return {i + 1}: DCS returned {t}, documented {doc_returns[i]}"
                )
        if issues:
            kind = "method" if instance else "function"
            out.append(f"{path} ({kind}): {'; '.join(issues)}")
    return out


def report_probe(schema: dict[str, Any], probe_path: str) -> None:
    """Print the probe disagreements as warnings (never fails)."""
    if not Path(probe_path).is_file():
        print(f"No argument probe at {probe_path}: signatures not compared")
        return
    with Path(probe_path).open(encoding="utf-8") as f:
        probe = json.load(f)
    found = probe_disagreements(schema, probe)
    probed = probe.get("probedOn") or probe.get("dcsVersion")
    print(
        f"\nArgument probe {probe_path} (DCS {probed}): "
        f"{len(found)} documented signature(s) disagree"
    )
    for line in found:
        print(f"WARNING: probe: {line}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("schema_file")
    p.add_argument(
        "dcs_api_file", nargs="+", help="API dump files; the first that exists is used"
    )
    p.add_argument(
        "--probe",
        help="argument probe (probe.json) to compare signatures with "
        "(default: probe.json next to the API dump used)",
    )
    a = p.parse_args()
    with Path(a.schema_file).open(encoding="utf-8") as f:
        schema = json.load(f)
    api = load_api(a.dcs_api_file)
    schema_s = extract_schema(schema, api)
    dcs_s = extract_dcs(api)
    errors_found = compare(schema_s, dcs_s)
    drift = enum_value_drift(schema, api)
    for line in drift:
        print(f"Enum value differs: {line}")
    errors_found = errors_found or bool(drift)
    used = next(path for path in a.dcs_api_file if Path(path).is_file())
    report_probe(schema, a.probe or str(Path(used).parent / "probe.json"))

    sys.exit(1 if errors_found else 0)


if __name__ == "__main__":
    main()
