import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from tools.merge import merge_tree
from tools.spec_types import PRIMITIVES, TypeRefError, parse_type, type_names

KEYS_WITH_TYPES = {"type", "returns", "arrayOf", "inherits", "ref"}
# The task wrappers (ComboTask, ControlledTask, Mission) keep their waypoint
# record, which no field references.
IGNORED_RELATIVE_DIRS = ["types/tasks"]
# The DcsDb.* types, which the merged schema leaves out: checked from source.
DCS_DB_DIR = "types/dcs-database"
# Types that should be ignored in the unused check
EXPLICITLY_IGNORED_TYPES = {
    "EventTypeMap"
}  # Types we want to keep even if not directly referenced


def load_spec(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as f:
        if str(path).endswith((".yaml", ".yml")):
            return yaml.safe_load(f)
        return json.load(f)


def _parses(type_ref: str) -> bool:
    try:
        parse_type(type_ref)
    except TypeRefError:
        return False
    return True


def _record(type_ref: str, path: list[str], refs: dict[str, set[str]]) -> None:
    """Every type name ``type_ref`` mentions, an unparseable one as itself."""
    try:
        names = type_names(parse_type(type_ref))
    except TypeRefError:
        names = [type_ref]
    for t in names:
        refs.setdefault(t, set()).add("/" + "/".join(path))


def record_refs(node: Any, path: list[str], refs: dict[str, set[str]]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            new_path = [*path, k]
            if k in KEYS_WITH_TYPES:
                if isinstance(v, str):
                    _record(v, new_path, refs)
                elif isinstance(v, list):
                    for idx, item in enumerate(v):
                        if isinstance(item, str):
                            _record(item, [*new_path, str(idx)], refs)
            record_refs(v, new_path, refs)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            record_refs(item, [*path, str(idx)], refs)


def collect_refs(spec: Any) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    record_refs(spec, [], refs)
    return refs


def find_duplicate_types(spec: Any) -> set[str]:
    names: dict[str, str] = {}
    dup: set[str] = set()
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


def collect_ignored_types(src_root: str) -> set[str]:
    ignored: set[str] = set()
    for rel in IGNORED_RELATIVE_DIRS:
        dir_path = Path(src_root) / rel
        if dir_path.is_dir():
            for root, _, files in os.walk(dir_path):
                for file in files:
                    if file.endswith((".yaml", ".yml")):
                        try:
                            data = load_spec(Path(root) / file)
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
    src = Path(args.src).absolute()
    if (src / DCS_DB_DIR).is_dir():
        db, _ = merge_tree(str(src), subdirs=[DCS_DB_DIR])
        spec.setdefault("types", {}).update(db.get("types", {}))
    defined_types: set[str] = set(spec.get("types", {}).keys())
    defined_globals: set[str] = set(spec.get("globals", {}).keys())
    allowed: set[str] = defined_types | defined_globals | PRIMITIVES
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
    invalid = {t for t in missing if not _parses(t)}
    if invalid:
        issues = True
        print("Invalid typeRefs:")
        for t in sorted(invalid):
            print(f"- {t!r}")
            for p in sorted(missing.pop(t)):
                print(f"    ↳ {p}")
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
