#!/usr/bin/env python3
"""
Merge YAML schema files into a single output file (JSON or YAML).
Usage: python merge.py <output_filepath> --root <dir> [--subdirs <subdir1> <subdir2>...] [-f format] [-v]
"""

import os
import sys
import yaml
import json
import argparse
import copy
from collections.abc import Mapping


def deep_merge(source, destination):
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


def resolve_inheritance(merged_data, verbose=False):
    """Resolve inheritance in merged_data['globals']."""
    merged_globals = merged_data.get("globals")
    if not merged_globals or not isinstance(merged_globals, dict):
        return

    # Helper function to merge members
    def merge_members(parent, child):
        merged = copy.deepcopy(parent)
        for mtype in ["instance", "static", "properties"]:
            if mtype in child:
                if mtype not in merged:
                    merged[mtype] = {}
                merged[mtype].update(child.get(mtype, {}))
        return merged

    # Helper function to get inherited members recursively
    def get_members(class_name, all_classes, cache, visited=None):
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

        # Get own members
        own_members = {
            t: class_data.get(t, {}) for t in ["instance", "static", "properties"]
        }
        for t in own_members:
            if not isinstance(own_members[t], dict):
                own_members[t] = {}

        # Get and merge parent members
        parents = class_data.get("inherits", [])
        if not isinstance(parents, list):
            parents = []

        combined = {"instance": {}, "static": {}, "properties": {}}
        for parent in parents:
            if parent in all_classes:
                parent_members = get_members(parent, all_classes, cache, visited.copy())
                combined = merge_members(combined, parent_members)

        final = merge_members(combined, own_members)
        cache[class_name] = final
        visited.remove(class_name)
        return final

    # Process all classes
    cache = {}
    for class_name in merged_globals:
        if class_name not in cache:
            get_members(class_name, merged_globals, cache)


def main():
    parser = argparse.ArgumentParser(description="Merge YAML schema files.")
    parser.add_argument("output_filepath", help="Output file path for merged schema")
    parser.add_argument(
        "--root", "-r", default=os.getcwd(), help="Root directory to search"
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

    # Find YAML files
    abs_root = os.path.abspath(args.root)
    ignored_files = [
        os.path.abspath(os.path.join(abs_root, f)) for f in args.ignore_files
    ]

    if not os.path.isdir(abs_root):
        print(f"✖ Root directory not found: {abs_root}")
        sys.exit(1)

    search_paths = (
        [os.path.join(abs_root, d) for d in args.subdirs]
        if args.subdirs
        else [abs_root]
    )
    search_paths = [p for p in search_paths if os.path.isdir(p)]

    # Process files
    merged_data, count = {}, 0
    for path in search_paths:
        for dirpath, _, filenames in os.walk(path):
            for filename in filenames:
                if not filename.endswith((".yaml", ".yml")):
                    continue

                filepath = os.path.join(dirpath, filename)
                abs_path = os.path.abspath(filepath)

                if not abs_path.startswith(abs_root):
                    if args.verbose:
                        print(f"Skipping file outside root: {filepath}")
                    continue

                if abs_path in ignored_files:
                    continue

                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if data:
                        merged_data = deep_merge(data, merged_data)
                        count += 1
                        if args.verbose:
                            print(f"Merged: {filepath}")
                except Exception as e:
                    print(f"✖ Error processing {filepath}: {e}")

    if count == 0:
        print("⚠️ No YAML files were found or processed.")
        return

    # Process inheritance and write output
    resolve_inheritance(merged_data, args.verbose)

    output_dir = os.path.dirname(args.output_filepath)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        with open(args.output_filepath, "w", encoding="utf-8") as outfile:
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
