import json
import argparse
import sys
from typing import Dict, Set, Any, List

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


def add_member(s: Dict[str, Set[str]], ns: str, m: str):
    s.setdefault(ns, set()).add(m)


def enum_literals(node: Dict[str, Any], ns: str, s: Dict[str, Set[str]], pref: str):
    if node.get("kind") == "enum" and "values" in node:
        for v in node["values"]:
            add_member(s, ns, f"{pref}.{v}")


def walk_table(t: Dict[str, Any], ns: str, s: Dict[str, Set[str]], pref: str = ""):
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


def harvest_parent(item: Dict[str, Any]) -> str | None:
    if "value" in item and isinstance(item["value"], str):
        return item["value"].strip()
    if "sub" in item and isinstance(item["sub"], dict):
        for sub in item["sub"].get("members", []):
            if sub.get("name") == "className_" and "value" in sub:
                return sub["value"].strip()
    return None


def process_members(
    members: List[Dict[str, Any]], ns: str, s: Dict[str, Set[str]], pref: str = ""
):
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


def build_parent_map(raw: Dict[str, Any]) -> Dict[str, str]:
    pm: Dict[str, str] = {}
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


def inherit(s: Dict[str, Set[str]], pm: Dict[str, str]):
    memo: Dict[str, Set[str]] = {}

    def anc(c: str) -> Set[str]:
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


def extract_dcs(api: Dict[str, Any], ignore_env: bool = True) -> Dict[str, Set[str]]:
    s: Dict[str, Set[str]] = {}
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


def extract_schema(schema: Dict[str, Any], api: Dict[str, Any]) -> Dict[str, Set[str]]:
    s: Dict[str, Set[str]] = {}
    api_struct = extract_dcs(api, ignore_env=False)
    canon = {f"{n}.{m}".lower(): f"{n}.{m}" for n, ms in api_struct.items() for m in ms}

    def add(ns: str, m: str):
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


def compare(schema_s: Dict[str, Set[str]], dcs_s: Dict[str, Set[str]]):
    sn, dn = set(schema_s), set(dcs_s)
    missing_namespace = False
    missing_members = False

    for ns in sorted(dn - sn):
        print(f"Namespace missing in schema: {ns}")
        missing_namespace = True

    for ns in sorted(sn - dn):
        print(f"Extra namespace in schema: {ns}")
        # Extra namespaces are just warnings, not errors

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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("schema_file")
    p.add_argument("dcs_api_file")
    a = p.parse_args()
    with open(a.schema_file, "r", encoding="utf-8") as f:
        schema = json.load(f)
    with open(a.dcs_api_file, "r", encoding="utf-8") as f:
        api = json.load(f)
    schema_s = extract_schema(schema, api)
    dcs_s = extract_dcs(api)
    errors_found = compare(schema_s, dcs_s)

    # Exit with code 1 if errors were found, 0 otherwise
    sys.exit(1 if errors_found else 0)


if __name__ == "__main__":
    main()
