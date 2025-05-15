import argparse
import json
import sys
import os
from typing import Any, Dict, List, Set
import yaml

PRIMITIVES: Set[str] = {
    "number",
    "string",
    "boolean",
    "table",
    "function",
    "any",
    "nil",
    "void",
    "enum",
}
KEYS_WITH_TYPES = {"type", "returns", "arrayOf", "inherits"}
IGNORED_RELATIVE_DIRS = ["types/commands", "types/tasks", "types/enrouteTasks"]
# Types that should be ignored in the unused check
EXPLICITLY_IGNORED_TYPES = {
    "EventTypeMap"
}  # Types we want to keep even if not directly referenced


def load_spec(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        if path.endswith((".yaml", ".yml")):
            return yaml.safe_load(f)
        return json.load(f)


def split_union(t: str) -> List[str]:
    out: List[str] = []
    for part in t.split("|"):
        token = part.strip()
        if token.endswith("[]"):
            token = token[:-2].strip()
        if token.startswith("map<") and token.endswith(">"):
            out.extend(split_union(token[4:-1].strip()))
        elif token:
            out.append(token)
    return out


def record_refs(node: Any, path: List[str], refs: Dict[str, Set[str]]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            new_path = path + [k]
            if k in KEYS_WITH_TYPES:
                if isinstance(v, str):
                    for t in split_union(v):
                        refs.setdefault(t, set()).add("/" + "/".join(new_path))
                elif isinstance(v, list):
                    for idx, item in enumerate(v):
                        if isinstance(item, str):
                            for t in split_union(item):
                                refs.setdefault(t, set()).add(
                                    "/" + "/".join(new_path + [str(idx)])
                                )
            record_refs(v, new_path, refs)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            record_refs(item, path + [str(idx)], refs)


def collect_refs(spec: Any) -> Dict[str, Set[str]]:
    refs: Dict[str, Set[str]] = {}
    record_refs(spec, [], refs)
    return refs


def find_duplicate_types(spec: Any) -> Set[str]:
    names: Dict[str, str] = {}
    dup: Set[str] = set()
    for t in spec.get("types", {}):
        lower_name = t.lower()
        if lower_name in names:
            dup.add(t)
            dup.add(names[lower_name])
        else:
            names[lower_name] = t
    g_lower = {g.lower() for g in spec.get("globals", {})}
    for t in spec.get("types", {}):
        if t.lower() in g_lower:
            dup.add(t)
    return dup


def collect_ignored_types(src_root: str) -> Set[str]:
    ignored: Set[str] = set()
    for rel in IGNORED_RELATIVE_DIRS:
        dir_path = os.path.join(src_root, rel)
        if os.path.isdir(dir_path):
            for root, _, files in os.walk(dir_path):
                for file in files:
                    if file.endswith((".yaml", ".yml")):
                        try:
                            data = load_spec(os.path.join(root, file))
                        except Exception:
                            continue
                        if (
                            isinstance(data, dict)
                            and "types" in data
                            and isinstance(data["types"], dict)
                        ):
                            ignored.update(data["types"].keys())
    return ignored


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("spec", nargs="?", default="dcs-world-api-schema.json")

    parser.add_argument("--src", default="dcs-world-schema")

    args = parser.parse_args()

    try:
        spec = load_spec(args.spec)
    except FileNotFoundError:
        print(f"Spec file not found: {args.spec}", file=sys.stderr)
        sys.exit(1)
    defined_types: Set[str] = set(spec.get("types", {}).keys())
    defined_globals: Set[str] = set(spec.get("globals", {}).keys())
    allowed: Set[str] = defined_types | defined_globals | PRIMITIVES
    refs = collect_refs(spec)
    missing = {t: paths for t, paths in refs.items() if t not in allowed}
    duplicates = find_duplicate_types(spec)
    referenced = {t for t in refs if t in defined_types}
    ignored_types = collect_ignored_types(args.src)
    unused = {
        t
        for t in defined_types
        if t not in referenced
        and "." not in t
        and t not in ignored_types
        and t not in EXPLICITLY_IGNORED_TYPES
    }
    issues = False
    if missing:
        issues = True
        print("Missing type definitions:")
        for t in sorted(missing):
            print(f"- {t}")
            for p in sorted(missing[t]):
                print(f"    ↳ {p}")
    if duplicates:
        issues = True
        print("Duplicate type definitions:")
        for t in sorted(duplicates):
            print(f"- {t}")
    if unused:
        issues = True
        print("Unused type definitions:")
        for t in sorted(unused):
            print(f"- {t}")
    if issues:
        sys.exit(1)
    print("All type definitions are valid, unique, and used.")
    sys.exit(0)


if __name__ == "__main__":
    main()
