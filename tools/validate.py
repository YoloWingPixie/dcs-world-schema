#!/usr/bin/env python3
import sys
import json
import argparse
import re
from pathlib import Path
from jsonschema import Draft7Validator, RefResolver
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.comments import CommentedMap

DEFAULT_SCHEMA_FILENAME = "dcs_yaml_schema.yaml"
_yaml = YAML(typ="safe")


def load_schema(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return (
            _yaml.load(f) if path.suffix.lower() in {".yaml", ".yml"} else json.load(f)
        )


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return _yaml.load(f)


def lc(node):
    return (node.lc.line + 1, node.lc.col + 1) if hasattr(node, "lc") else (None, None)


def collect(paths):
    out = []
    for p in paths:
        p = Path(p)
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out.extend(p.rglob("*.yaml"))
            out.extend(p.rglob("*.yml"))
    return sorted(set(out))


def tree_lines(segs, msg, line=None, col=None):
    segs = [s for s in segs if s]
    lines = []
    for i, seg in enumerate(segs):
        indent = "  " * i
        if i < len(segs) - 1:
            lines.append(f"{indent}└─ {seg}")
        else:
            loc = f" (line {line}, col {col})" if line else ""
            lines.append(f"{indent}└─ {seg} – {msg}{loc}")
    return lines


def collect_errors(entry, validator, base=""):
    errs = []
    for err in sorted(validator.iter_errors(entry), key=lambda e: (e.path, e.message)):
        full_path = list(filter(None, base.split("/"))) + list(err.path)
        line_num, c = lc(err.instance)
        errs.extend(tree_lines(full_path, err.message, line_num, c))
        if err.validator == "additionalProperties" and isinstance(
            err.instance, CommentedMap
        ):
            m = re.search(r"\((.*?)\s+were unexpected\)", err.message)
            if m:
                for k in [s.strip().strip("'\"") for s in m.group(1).split(",")]:
                    info = err.instance.lc.key(k)
                    kl, kc = (
                        (info[0] + 1, info[1] + 1)
                        if info and len(info) >= 2
                        else (None, None)
                    )
                    errs.extend(
                        tree_lines(
                            full_path + [k], f"unexpected property '{k}'", kl, kc
                        )
                    )
    return errs


def build_validators(schema):
    resolver = RefResolver.from_schema(schema)
    return (
        Draft7Validator(schema, resolver=resolver),
        Draft7Validator({"$ref": "#/definitions/globalEntry"}, resolver=resolver),
        Draft7Validator({"$ref": "#/definitions/typeEntry"}, resolver=resolver),
    )


def validate_file(fp, data, v_root, v_global, v_type):
    errors = []
    if isinstance(data, dict) and ("globals" in data or "types" in data):
        if "globals" in data:
            for n, e in data["globals"].items():
                errors.extend(collect_errors(e, v_global, f"globals/{n}"))
        if "types" in data:
            for n, e in data["types"].items():
                errors.extend(collect_errors(e, v_type, f"types/{n}"))
        return errors
    parts = {p.lower() for p in fp.parts}
    validator = v_global if "globals" in parts else v_type if "types" in parts else None
    if validator is None:
        validator = (
            v_global
            if v_global.is_valid(data)
            else v_type
            if v_type.is_valid(data)
            else v_root
        )
    errors.extend(collect_errors(data, validator))
    return errors


def resolve_schema(paths, explicit):
    if explicit:
        return Path(explicit)
    if len(paths) == 1 and Path(paths[0]).is_dir():
        candidate = Path(paths[0]) / DEFAULT_SCHEMA_FILENAME
        if candidate.exists():
            return candidate
    return Path.cwd() / DEFAULT_SCHEMA_FILENAME


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default=".")
    ap.add_argument("--schema")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    paths = [args.target]
    schema_path = resolve_schema(paths, args.schema)
    if not schema_path.exists():
        print(f"✖ Schema not found: {schema_path}")
        sys.exit(1)

    files = collect(paths)
    if not files:
        print("✖ No YAML files found")
        sys.exit(1)

    root_schema = load_schema(schema_path)
    v_root, v_global, v_type = build_validators(root_schema)

    all_ok = True
    for fp in files:
        try:
            data = load_yaml(fp)
        except YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            loc = f" (line {mark.line + 1}, col {mark.column + 1})" if mark else ""
            print(
                f"✖ YAML parse error in {fp}{loc}: {e.problem if hasattr(e, 'problem') else e}"
            )
            all_ok = False
            continue
        except Exception as e:
            print(f"✖ Error reading {fp}: {e}")
            all_ok = False
            continue

        errs = validate_file(fp, data, v_root, v_global, v_type)
        if errs:
            print(f"❌ {fp}")
            for line in errs:
                print(f"    {line}")
            all_ok = False
        else:
            if not args.quiet:
                print(f"✅ {fp}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
