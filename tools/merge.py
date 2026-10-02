#!/usr/bin/env python3
"""
Merge YAML schema files into a single output file (JSON or YAML).
Usage: python -m tools.merge <output_filepath> --root <dir> [--subdirs <subdir1> <subdir2>...] [-f format] [-v]

The output leaves out the ``DcsDb.*`` types (``spec_types.DCS_DB_PREFIX``).
"""

import argparse
import copy
import json
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from tools.spec_types import DCS_DB_PREFIX, without_types


def deep_merge(
    source: Mapping[str, Any], destination: dict[str, Any]
) -> dict[str, Any]:
    """Deeply merge source dict into destination dict."""
    for key, value in source.items():
        if isinstance(value, Mapping):
            node = destination.setdefault(key, {})
            deep_merge(value, node)
        elif isinstance(value, list):
            if key not in destination or not isinstance(destination[key], list):
                destination[key] = []
            destination[key].extend(
                item for item in value if item not in destination[key]
            )
        else:
            destination[key] = value
    return destination


Members = dict[str, dict[str, Any]]


def resolve_inheritance(merged_data: dict[str, Any], verbose: bool = False) -> None:
    """Resolve inheritance in merged_data['globals']."""
    merged_globals = merged_data.get("globals")
    if not merged_globals or not isinstance(merged_globals, dict):
        return

    def merge_members(parent: Members, child: Members) -> Members:
        merged = copy.deepcopy(parent)
        for mtype in ["instance", "static", "properties"]:
            if mtype in child:
                if mtype not in merged:
                    merged[mtype] = {}
                merged[mtype].update(child.get(mtype, {}))
        return merged

    def get_members(
        class_name: str,
        all_classes: dict[str, Any],
        cache: dict[str, Members],
        visited: set[str] | None = None,
    ) -> Members:
        visited = visited or set()
        if class_name in visited:
            return {"instance": {}, "static": {}, "properties": {}}
        if class_name in cache:
            return cache[class_name]

        visited.add(class_name)
        class_data = all_classes.get(class_name, {})
        if not isinstance(class_data, dict):
            visited.remove(class_name)
            cache[class_name] = {"instance": {}, "static": {}, "properties": {}}
            return cache[class_name]

        own_members: Members = {
            t: class_data.get(t, {}) for t in ["instance", "static", "properties"]
        }
        for t in own_members:
            if not isinstance(own_members[t], dict):
                own_members[t] = {}

        parents = class_data.get("inherits", [])
        if not isinstance(parents, list):
            parents = []

        combined: Members = {"instance": {}, "static": {}, "properties": {}}
        for parent in parents:
            if parent in all_classes:
                parent_members = get_members(parent, all_classes, cache, visited.copy())
                combined = merge_members(combined, parent_members)

        final = merge_members(combined, own_members)
        cache[class_name] = final
        visited.remove(class_name)
        return final

    cache: dict[str, Members] = {}
    for class_name in merged_globals:
        if class_name not in cache:
            get_members(class_name, merged_globals, cache)


# Globals of the other Lua environments (the API dump's hooks, server and
# export states). Each is its own spec: the main one is mission scripting.
ENV_DIRS = ("globals/export", "globals/hooks", "globals/server")


def merge_tree(
    abs_root: str,
    subdirs: list[str] | None = None,
    ignore_files: Iterable[str] = (),
    verbose: bool = False,
) -> tuple[dict[str, Any], int]:
    """(merged spec, file count) of every YAML file under ``abs_root`` (only
    ``subdirs`` when given, else all but ``ENV_DIRS``)."""
    root = Path(abs_root)
    ignored_files = [os.path.normpath((root / f).absolute()) for f in ignore_files]
    search_paths = [root / d for d in subdirs] if subdirs else [root]
    search_paths = [p for p in search_paths if p.is_dir()]
    excluded = set() if subdirs else {os.path.normpath(root / d) for d in ENV_DIRS}

    merged_data: dict[str, Any] = {}
    count = 0
    for path in search_paths:
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [
                d
                for d in dirnames
                if os.path.normpath(Path(dirpath) / d) not in excluded
            ]
            for filename in filenames:
                if not filename.endswith((".yaml", ".yml")):
                    continue

                filepath = Path(dirpath) / filename
                abs_path = os.path.normpath(filepath.absolute())

                if not abs_path.startswith(abs_root):
                    if verbose:
                        print(f"Skipping file outside root: {filepath}")
                    continue

                if abs_path in ignored_files:
                    continue

                try:
                    with filepath.open(encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if data:
                        merged_data = deep_merge(data, merged_data)
                        count += 1
                        if verbose:
                            print(f"Merged: {filepath}")
                except Exception as e:
                    print(f"✖ Error processing {filepath}: {e}")
    resolve_inheritance(merged_data, verbose)
    return merged_data, count


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge YAML schema files.")
    parser.add_argument("output_filepath", help="Output file path for merged schema")
    parser.add_argument(
        "--root", "-r", default=Path.cwd(), help="Root directory to search"
    )
    parser.add_argument(
        "--subdirs", "-s", nargs="*", help="Specific subdirectories to search"
    )
    parser.add_argument(
        "--format", "-f", choices=["json", "yaml"], default="json", help="Output format"
    )
    parser.add_argument(
        "--ignore-files", "-i", nargs="*", default=[], help="Files to ignore"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    abs_root = os.path.normpath(Path(args.root).absolute())
    if not Path(abs_root).is_dir():
        print(f"✖ Root directory not found: {abs_root}")
        sys.exit(1)
    merged_data, count = merge_tree(
        abs_root, args.subdirs, args.ignore_files, args.verbose
    )
    if count == 0:
        print("⚠️ No YAML files were found or processed.")
        return
    if "types" in merged_data:
        merged_data = without_types(merged_data, DCS_DB_PREFIX)

    output = Path(args.output_filepath)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        with output.open("w", encoding="utf-8") as outfile:
            if args.format == "json":
                json.dump(merged_data, outfile, indent=2, ensure_ascii=False)
            else:
                yaml.dump(
                    merged_data, outfile, allow_unicode=True, sort_keys=False, indent=2
                )
        print(
            f"✅ Successfully merged {count} YAML file(s) into: {args.output_filepath}"
        )
    except Exception as e:
        print(f"✖ Error writing output file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
