"""tools/conventions.py: comments, description style, entity names and unit
suffixes in the hand-written schema YAML; generated files are skipped."""

from __future__ import annotations

from pathlib import Path

from conftest import write

from tools.conventions import check_tree

ENTITY = """\
globals: {}
types:
  Entity.Sample:
    kind: record
    description: "Distances in metres."
    fields:
      lengthM:
        type: number
        description: "Optional `length`."
      massKg:
        type: number | nil
        description: "Optional `mass`."
      speedMs:
        type: number
        description: "Optional `speed`, m/s."
      rangeKm:
        type: number[]
        description: "Optional `[min, max]`, kilometres."
      weight:
        type: number
        description: "Optional `weight`, kg."
      economyDistance:
        type: number
        description: "Optional `economy_distance`, raw (metres by their values)."
      latitude:
        type: number
        description: "Degrees north."
      position:
        type: number[]
        description: "`{x, y, z}`, metres."
      max_v:
        type: string
        description: "Snake case."
      _source:
        type: any
        description: "Provenance."
  Entity.lower:
    kind: record
    description: "Lowercase segment."
    fields: {}
"""


def test_entity_names_and_unit_suffixes(tmp_path: Path) -> None:
    write(tmp_path / "types/entities/Sample.record.yaml", ENTITY)
    assert check_tree(tmp_path, {}) == [
        "types/entities/Sample.record.yaml: Entity.Sample.massKg: unit suffix 'Kg' "
        "but neither it nor its type's description states the unit",
        "types/entities/Sample.record.yaml: Entity.Sample.weight: description "
        "states a unit but the name has no unit suffix",
        "types/entities/Sample.record.yaml: Entity.Sample.max_v: field name is "
        "not camelCase",
        "types/entities/Sample.record.yaml: Entity.lower: entity type name is not "
        "Entity.<PascalCase>",
    ]


def test_published_names_skip_only_their_rule(tmp_path: Path) -> None:
    write(tmp_path / "types/entities/Sample.record.yaml", ENTITY)
    problems = check_tree(
        tmp_path,
        {
            "Entity.Sample.max_v": "camelCase",
            "Entity.Sample.weight": "camelCase",
            "Entity.Sample.gone": "camelCase",
        },
    )
    assert not any("max_v" in p for p in problems)
    assert any("Entity.Sample.weight: description states a unit" in p for p in problems)
    assert problems[-2:] == [
        "PUBLISHED_NAMES Entity.Sample.weight: breaks no camelCase rule (remove it)",
        "PUBLISHED_NAMES Entity.Sample.gone: breaks no camelCase rule (remove it)",
    ]


def test_descriptions_and_comments(tmp_path: Path) -> None:
    write(
        tmp_path / "globals/thing.singleton.yaml",
        """\
globals:
  # header
  thing:
    kind: singleton
    description: "no period"
    environment: [Server] # trailing
    static:
      run:
        description: |
          Block with a #hash in Lua.
        returns: void
        examples:
          - code: "for i = 1, #t do end"
            description: ""
types: {}
""",
    )
    write(tmp_path / "types/x.generated.yaml", "# generated\ntypes: {}\n")
    write(tmp_path / "types/country.enum.yaml", "# generated\ntypes: {}\n")
    assert check_tree(tmp_path, {}) == [
        "globals/thing.singleton.yaml:2: comment # header",
        "globals/thing.singleton.yaml:6: comment # trailing",
        "globals/thing.singleton.yaml: globals/thing: description starts lowercase",
        "globals/thing.singleton.yaml: globals/thing/static/run: description has "
        "leading or trailing whitespace",
        "globals/thing.singleton.yaml: globals/thing/static/run/examples/0: "
        "empty description",
    ]
