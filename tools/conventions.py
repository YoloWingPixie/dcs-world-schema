"""Check the hand-written schema YAML against the conventions in CONTRIBUTING.md.

- No comments.
- Every description is non-empty, has no surrounding whitespace, does not
  start lowercase and ends with a period.
- Entity types (types/entities/) are ``Entity.`` + PascalCase segments; their
  fields are camelCase (``_source`` is the provenance map).
- An entity number field named with a unit suffix (``massKg``) states that
  unit in its description or its type's; a scalar one whose description states
  a unit carries a suffix, unless the value is kept raw or is a coordinate
  (``x``, ``latitude``).

Generated files (``*.generated*.yaml``, ``types/country.enum.yaml``) are skipped.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.tokens import CommentToken

from tools.datamine.dcs_constants import COUNTRY_SCHEMA, TYPES_DIR
from tools.spec_types import Array, Primitive, TypeRefError, parse_type, strip_null

GENERATED = (COUNTRY_SCHEMA.relative_to(TYPES_DIR.parent).as_posix(),)
ENTITY_DIR = "types/entities"

ENTITY_TYPE = re.compile(r"Entity(\.[A-Z][A-Za-z0-9]*)+")
CAMEL_CASE = re.compile(r"_source|[a-z][a-zA-Z0-9]*")

# Name suffix -> how a description states the unit; longest suffix first.
UNIT_SUFFIXES: dict[str, str] = {
    "KgS": r"kg/s",
    "RadS": r"rad/s|radians per second",
    "Kmh": r"km/h|kilometres per hour",
    "Deg": r"degrees",
    "Rad": r"radians",
    "MHz": r"megahertz",
    "KHz": r"kilohertz",
    "Hz": r"hertz",
    "Kg": r"kilograms|kg",
    "Km": r"kilometres",
    "Ms": r"m/s",
    "M2": r"square metres",
    "M": r"metres|meters",
    "S": r"seconds",
}
UNIT_TEXT = {
    suffix: re.compile(rf"(?<![\w/])(?:{words})(?![\w/])", re.IGNORECASE)
    for suffix, words in UNIT_SUFFIXES.items()
}
RAW = re.compile(r"\braw\b")
COORDINATES = frozenset({"x", "y", "z", "latitude", "longitude"})
# Field rules, as PUBLISHED_NAMES name them: a camelCase name, a unit suffix
# whose unit is stated, a stated unit that has a suffix.
CAMEL = "camelCase"
STATED_UNIT = "statedUnit"
SUFFIXED_UNIT = "suffixedUnit"
# Published names and the rule each breaks; renaming them changes the data shape.
PUBLISHED_NAMES = {
    "Entity.ActionManeuverParam.min_v": CAMEL,
    "Entity.ActionManeuverParam.max_v": CAMEL,
    "Entity.Beacon.direction": SUFFIXED_UNIT,
    "Entity.MagneticVariation.degrees": SUFFIXED_UNIT,
    "Entity.MapProjection.centralMeridian": SUFFIXED_UNIT,
    "Entity.MapProjection.latitudeOfOrigin": SUFFIXED_UNIT,
    "Entity.MapProjection.falseEasting": SUFFIXED_UNIT,
    "Entity.MapProjection.falseNorthing": SUFFIXED_UNIT,
}


def is_generated(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    return ".generated" in path.name or rel in GENERATED


def _tokens(node: Any) -> Iterator[CommentToken]:
    if isinstance(node, CommentToken):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _tokens(value)
    elif isinstance(node, list):
        for item in node:
            yield from _tokens(item)


def comments(node: Any) -> Iterator[tuple[int, str]]:
    """``(1-based line, text)`` of each ``#`` comment in a round-trip loaded
    document. A token's mark is on its first comment line (rarely a blank
    line before it); its value runs on from there, after any line breaks
    that end earlier lines."""
    ca = getattr(node, "ca", None)
    if ca is not None:
        for slot in ("comment", "items", "end", "pre"):
            for token in _tokens(getattr(ca, slot, None)):
                lines = token.value.lstrip("\n").split("\n")
                for i, line in enumerate(lines):
                    if line.strip().startswith("#"):
                        yield token.start_mark.line + i + 1, line.strip()
    if isinstance(node, dict):
        for value in node.values():
            yield from comments(value)
    elif isinstance(node, list):
        for item in node:
            yield from comments(item)


def description_problem(text: str) -> str | None:
    if not text.strip():
        return "empty description"
    if text != text.strip():
        return "description has leading or trailing whitespace"
    if text[0].islower():
        return "description starts lowercase"
    if not text.endswith("."):
        return "description does not end with a period"
    return None


def check_descriptions(node: Any, path: list[str]) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "description" and isinstance(value, str):
                problem = description_problem(value)
                if problem:
                    yield f"{'/'.join(path)}: {problem}"
            else:
                yield from check_descriptions(value, [*path, str(key)])
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from check_descriptions(item, [*path, str(i)])


def number_kind(type_ref: str) -> str | None:
    """``"scalar"`` or ``"array"`` for a (nil-able) number or number[] typeRef."""
    try:
        node, _ = strip_null(parse_type(type_ref))
    except TypeRefError:
        return None
    if node == Primitive("number"):
        return "scalar"
    if node == Array(Primitive("number")):
        return "array"
    return None


def unit_suffix(name: str) -> str | None:
    return next((s for s in UNIT_SUFFIXES if name.endswith(s)), None)


def check_entity_field(
    type_description: str, name: str, field: dict[str, Any]
) -> Iterator[tuple[str, str]]:
    """``(rule, problem)`` of each rule the field breaks."""
    if not CAMEL_CASE.fullmatch(name):
        yield CAMEL, "field name is not camelCase"
    kind = number_kind(field.get("type", ""))
    if kind is None:
        return
    description = field.get("description", "")
    suffix = unit_suffix(name)
    if suffix:
        unit = UNIT_TEXT[suffix]
        if not unit.search(description) and not unit.search(type_description):
            yield (
                STATED_UNIT,
                f"unit suffix {suffix!r} but neither it nor its type's description states the unit",
            )
    elif (
        kind == "scalar"
        and name not in COORDINATES
        and not RAW.search(description)
        and any(unit.search(description) for unit in UNIT_TEXT.values())
    ):
        yield SUFFIXED_UNIT, "description states a unit but the name has no unit suffix"


def check_entities(
    types: dict[str, Any], published: dict[str, str], matched: set[str]
) -> Iterator[str]:
    for type_name, entry in types.items():
        if not ENTITY_TYPE.fullmatch(type_name):
            yield f"{type_name}: entity type name is not Entity.<PascalCase>"
        type_description = entry.get("description", "")
        for name, field in (entry.get("fields") or {}).items():
            where = f"{type_name}.{name}"
            for rule, problem in check_entity_field(type_description, name, field):
                if published.get(where) == rule:
                    matched.add(where)
                else:
                    yield f"{where}: {problem}"


def check_file(
    path: Path, root: Path, published: dict[str, str], matched: set[str]
) -> list[str]:
    rel = path.relative_to(root).as_posix()
    spec = YAML().load(path.read_text(encoding="utf-8")) or {}
    found = sorted(set(comments(spec)))  # a token can hang off two nodes
    problems = [f"{rel}:{line}: comment {text}" for line, text in found]
    problems += [f"{rel}: {p}" for p in check_descriptions(spec, [])]
    if rel.startswith(f"{ENTITY_DIR}/"):
        types = spec.get("types") or {}
        problems += [f"{rel}: {p}" for p in check_entities(types, published, matched)]
    return problems


def check_tree(root: Path, published: dict[str, str] = PUBLISHED_NAMES) -> list[str]:
    """Every problem in ``root``'s hand-written files; a ``published`` name
    that breaks none of the rules it is exempt from is one too."""
    matched: set[str] = set()
    problems = [
        problem
        for path in sorted(root.rglob("*.yaml"))
        if not is_generated(path, root)
        for problem in check_file(path, root, published, matched)
    ]
    problems += [
        f"PUBLISHED_NAMES {name}: breaks no {rule} rule (remove it)"
        for name, rule in published.items()
        if name not in matched
    ]
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", type=Path, default=Path("dcs-world-schema"))
    args = parser.parse_args()
    problems = check_tree(args.root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        sys.exit(f"{len(problems)} convention problem(s) in {args.root}")
    print(f"{args.root}: conventions OK")


if __name__ == "__main__":
    main()
