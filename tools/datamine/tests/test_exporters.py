"""The TS / EmmyLua / Go / Python exporters render ``kind: record`` fields and
leave out the ``Sample.*`` reference-data types."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from tools import (
    export_golang,
    export_jsonschema,
    export_lua,
    export_python,
    export_selene_yaml,
    export_typescript,
    merge,
)
from tools.merge import merge_tree
from tools.spec_types import (
    DCS_DB_PREFIX,
    TYPE_ROOT_GLOBALS,
    Array,
    Literal,
    Map,
    Primitive,
    Ref,
    TypeRefError,
    Union,
    api_spec,
    format_type,
    is_type_only,
    parse_type,
    runtime_roots,
    strip_null,
    type_names,
    union_parts,
)

REPO = Path(__file__).resolve().parents[3]

# A small spec exercising every typeRef shape a record field may use.
SAMPLE: dict[str, Any] = {
    "globals": {},
    "types": {
        "Vec3": {
            "kind": "record",
            "description": "A 3D point.",
            "fields": {
                "x": {"type": "number", "description": "North."},
                "y": {"type": "number"},
                "z": {"type": "number"},
            },
            "required": ["x", "y", "z"],
        },
        "Sample.AircraftKind": {
            "kind": "enum",
            "description": "Airframe class.",
            "values": {"airplane": "airplane", "helicopter": "helicopter"},
        },
        "Sample.Gun": {
            "kind": "record",
            "description": "A gun.",
            "fields": {"id": {"type": "string"}},
            "required": ["id"],
        },
        "Sample.Aircraft": {
            "kind": "record",
            "description": "An aircraft.",
            "fields": {
                "id": {"type": "string", "description": "Type name."},
                "kind": {"type": "Sample.AircraftKind"},
                "flyable": {"type": "boolean"},
                "crew": {"type": "number"},
                "gun": {"type": "Sample.Gun"},
                "guns": {"type": "Sample.Gun[]"},
                "origin": {"type": "Vec3 | nil"},
                "extra": {"type": "any"},
                "loads": {"type": "map<string, number>"},
                "_source": {"type": "table"},
            },
            "required": ["id", "kind", "flyable", "guns", "origin"],
        },
        "Sample.YearRange": {
            "kind": "record",
            "description": "Service years.",
            "fields": {"from": {"type": "number"}, "to": {"type": "number | nil"}},
            "required": ["from"],
        },
    },
}


def _export(
    fn: Callable[..., None], schema: dict[str, Any], path: Path, *args: Any
) -> str:
    fn(copy.deepcopy(schema), str(path), *args)
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    merged, count = merge_tree(str(REPO / "dcs-world-schema"))
    assert count
    # as the exporters read it (task merge:json)
    return cast(dict[str, Any], json.loads(json.dumps(merged)))


# --- TypeScript ------------------------------------------------------------


def test_typescript_sample_record_fields(tmp_path: Path) -> None:
    out = _export(export_typescript.export_to_typescript, SAMPLE, tmp_path / "a.d.ts")
    assert "declare interface Vec3 {" in out
    assert "    /** North. */\n    x: number;" in out
    assert "declare namespace Sample {" in out
    body = out[out.index("interface Aircraft {") :]
    body = body[: body.index("}")]
    for line in (
        "id: string;",
        "kind: Sample.AircraftKind;",
        "flyable: boolean;",
        "crew?: number;",
        "gun?: Sample.Gun;",
        "guns: Array<Sample.Gun>;",
        "origin?: Vec3;",  # ``| nil`` -> optional, not a nullable member
        "extra?: any;",
        "loads?: Record<string, number>;",
        "_source?: Record<string, any>;",
    ):
        assert line in body, line
    assert "from: number;" in out and "to?: number;" in out
    assert "No properties or methods defined" not in out


def test_typescript_real_spec_records(spec: dict[str, Any], tmp_path: Path) -> None:
    out = _export(export_typescript.export_to_typescript, spec, tmp_path / "a.d.ts")
    _assert_fields_rendered(
        out,
        spec,
        "DcsTask.Task.Orbit",
        start="interface Orbit {",
        line=lambda n, opt: f"{n}{'?' if opt else ''}: ",
    )
    _assert_fields_rendered(
        out,
        spec,
        "Vec3",
        start="declare interface Vec3 {",
        line=lambda n, opt: f"{n}{'?' if opt else ''}: ",
    )


# --- EmmyLua ---------------------------------------------------------------


def test_lua_sample_record_fields(tmp_path: Path) -> None:
    out = _export(export_lua.export_to_lua, SAMPLE, tmp_path / "a.lua")
    assert "---@field x number North." in out
    for line in (
        "---@field id string Type name.",
        "---@field kind Sample.AircraftKind",
        "---@field crew? number",
        "---@field gun? Sample.Gun",
        "---@field guns Sample.Gun[]",
        "---@field origin? Vec3",
        "---@field extra? any",
        "---@field loads? table<string, number>",
        "---@field to? number",
    ):
        assert line in out, line
    assert "Generated on:" not in out  # deterministic header


def test_lua_field_names_that_are_not_lua_names_are_quoted() -> None:
    required = {"type", "Ka-50"}
    field = {"type": "number"}
    assert export_lua.record_field_annotation("type", field, required) == (
        "type",
        "number",
    )
    assert export_lua.record_field_annotation("Ka-50", field, required) == (
        '["Ka-50"]',
        "number",
    )
    assert export_lua.record_field_annotation("end", field, set()) == (
        '["end"]',
        "number|nil",
    )
    assert export_lua.record_field_annotation("x y", field, set()) == (
        '["x y"]',
        "number|nil",
    )


def test_lua_real_spec_records(spec: dict[str, Any], tmp_path: Path) -> None:
    out = _export(export_lua.export_to_lua, spec, tmp_path / "a.lua")
    for name in ("DcsTask.Task.Orbit", "Vec3"):
        _assert_fields_rendered(
            out,
            spec,
            name,
            start=f"---@class {name}\n",
            line=lambda n, opt: f"---@field {n}{'?' if opt else ''} ",
        )


# --- Go --------------------------------------------------------------------


def test_go_sample_record_fields(tmp_path: Path) -> None:
    out = _export(export_golang.export_to_golang, SAMPLE, tmp_path / "a.go")
    assert "type Vec3 struct {" in out
    assert '\tX float64 `json:"x"`' in out
    assert "type SampleAircraftKind string" in out
    body = out[out.index("type SampleAircraft struct {") :]
    body = body[: body.index("\n}")]
    for line in (
        '\tId string `json:"id"`',
        '\tKind SampleAircraftKind `json:"kind"`',
        '\tCrew *float64 `json:"crew,omitempty"`',
        '\tGun *SampleGun `json:"gun,omitempty"`',
        '\tGuns []SampleGun `json:"guns"`',
        '\tOrigin *Vec3 `json:"origin,omitempty"`',
        '\tExtra interface{} `json:"extra,omitempty"`',
        '\tLoads map[string]float64 `json:"loads,omitempty"`',
        '\tSource map[string]interface{} `json:"_source,omitempty"`',
    ):
        assert line in body, line


def test_go_real_spec_records(spec: dict[str, Any], tmp_path: Path) -> None:
    out = _export(export_golang.export_to_golang, spec, tmp_path / "a.go")
    for name, go_name in (("DcsTask.Task.Orbit", "DcsTaskTaskOrbit"), ("Vec3", "Vec3")):
        record = spec["types"][name]
        body = out[out.index(f"type {go_name} struct {{") :]
        body = body[: body.index("\n}")]
        tags = re.findall(r'`json:"([^"]+)"`', body)
        expected = [
            f"{f},omitempty" if _optional(record, f) else f for f in record["fields"]
        ]
        assert tags == expected


# --- Python ----------------------------------------------------------------


def _import(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[name]
    return module


def test_python_sample_record_fields(tmp_path: Path) -> None:
    path = tmp_path / "sample_api.py"
    out = _export(export_python.export_to_python, SAMPLE, path)
    assert "class Vec3(TypedDict):" in out
    mod = _import(path, "sample_api")
    aircraft = mod.Sample_Aircraft
    assert aircraft.__required_keys__ == {"id", "kind", "flyable", "guns"}
    assert aircraft.__optional_keys__ == {
        "crew",
        "gun",
        "origin",
        "extra",
        "loads",
        "_source",
    }
    hints = typing.get_type_hints(aircraft, vars(mod))
    assert hints["kind"] is mod.Sample_AircraftKind
    assert hints["guns"] == mod.List[mod.Sample_Gun]
    assert hints["origin"] is mod.Vec3
    assert hints["loads"] == mod.Dict[str, float]
    # ``from`` is a keyword: functional TypedDict form
    years = mod.Sample_YearRange
    assert years.__required_keys__ == {"from"}
    assert years.__optional_keys__ == {"to"}


def test_python_real_spec_records(spec: dict[str, Any], tmp_path: Path) -> None:
    path = tmp_path / "real_api.py"
    _export(export_python.export_to_python, spec, path)
    mod = _import(path, "real_api")
    for name, py_name in (
        ("DcsTask.Task.Orbit", "DcsTask_Task_Orbit"),
        ("Vec3", "Vec3"),
    ):
        record = spec["types"][name]
        td = getattr(mod, py_name)
        required = {f for f in record["fields"] if not _optional(record, f)}
        assert td.__required_keys__ == required
        assert td.__optional_keys__ == set(record["fields"]) - required
        typing.get_type_hints(td, vars(mod))  # every referenced type resolves


# --- String literal types ---------------------------------------------------

# Records told apart by a literal ``id`` and their union, as DcsTask.* are.
LITERAL: dict[str, Any] = {
    "globals": {},
    "types": {
        "Sample.Orbit": {
            "kind": "record",
            "fields": {
                "id": {"type": '"Orbit"'},
                "pattern": {"type": '"Circle" | "Race-Track" | nil'},
            },
            "required": ["id"],
        },
        "Sample.Hold": {
            "kind": "record",
            "fields": {"id": {"type": '"Hold"'}},
            "required": ["id"],
        },
        "Sample.AnyTask": {
            "kind": "union",
            "description": "Any task.",
            "anyOf": ["Sample.Orbit", "Sample.Hold"],
        },
    },
}
_PACKAGE_TSC = REPO / "packages" / "typescript" / "node_modules" / ".bin" / "tsc"
TSC = str(_PACKAGE_TSC) if _PACKAGE_TSC.is_file() else shutil.which("tsc")


def test_parse_type_shapes() -> None:
    assert parse_type('"Orbit"') == Literal("Orbit")
    assert parse_type("Orbit") == Ref("Orbit")
    assert parse_type("Unit | nil") == Union((Ref("Unit"), Primitive("nil")))
    assert parse_type("number[][]") == Array(Array(Primitive("number")))
    assert parse_type("map<Vec3>") == Map(Primitive("string"), Ref("Vec3"))
    # ``|`` and ``,`` inside ``map<..>`` belong to the map, not the outer union.
    assert parse_type("map<string, A | B> | nil") == Union(
        (Map(Primitive("string"), Union((Ref("A"), Ref("B")))), Primitive("nil"))
    )
    assert parse_type("map<number, map<string, X>>") == Map(
        Primitive("number"), Map(Primitive("string"), Ref("X"))
    )
    assert parse_type("(A | B)[]") == Array(Union((Ref("A"), Ref("B"))))
    assert union_parts("map<A | B> | C[]") == ["map<A | B>", "C[]"]
    assert strip_null(parse_type("A | nil")) == (Ref("A"), True)
    assert strip_null(parse_type("nil")) == (None, True)
    assert type_names(parse_type('map<number, A | B[]> | "x" | A | nil')) == [
        "number",
        "A",
        "B",
        "nil",
    ]


@pytest.mark.parametrize(
    "text",
    ['"Orbit"', "Unit | nil", "map<number, A[]>", "(A | B)[]", "map<A | B>[]"],
)
def test_format_type_round_trips(text: str) -> None:
    node = parse_type(text)
    assert parse_type(format_type(node)) == node
    assert format_type(node) == text


@pytest.mark.parametrize(
    "text",
    ["", "A |", "map<A", "A[", '"open', '"a|b"', "(A", "A B", "map<>", "A..B"],
)
def test_parse_type_rejects(text: str) -> None:
    with pytest.raises(TypeRefError, match=re.escape(repr(text))):
        parse_type(text)


def test_selene_literal_unions_are_strings() -> None:
    args = export_selene_yaml.build_function_args(
        [
            {"name": "a", "type": '"Circle" | "Race-Track"'},
            {"name": "b", "type": "string | nil"},
            {"name": "c", "type": "map<string, number>"},
        ]
    )
    assert args == [
        {"type": "string"},
        {"type": {"display": "string | nil"}},
        {"type": {"display": "map<string, number>"}},
    ]


def test_go_literal_union_map_values() -> None:
    assert export_golang.map_type('map<"A" | "B">') == "map[string]string"
    assert export_golang.map_type('"A" | "B"') == "string"
    assert export_golang.map_type("map<number, Vec3>") == "map[float64]Vec3"
    assert export_golang.record_field_type('map<"A" | "B"> | nil') == (
        "map[string]string",
        True,
    )


def test_map_keys_and_nested_unions() -> None:
    # ``map<V>`` has string keys in every output.
    assert export_lua.map_type("map<number>") == "table<string, number>"
    assert export_lua.map_type("map<A | B>") == "table<string, A|B>"
    assert export_lua.map_type("(B | A)[]") == "(A|B)[]"
    assert export_typescript.map_type("map<number, string>") == (
        "Record<number, string>"
    )
    assert export_python.map_type("map<string, map<string, X>>") == (
        "Dict[str, Dict[str, X]]"
    )


def test_typescript_literal_types(tmp_path: Path) -> None:
    out = _export(export_typescript.export_to_typescript, LITERAL, tmp_path / "a.d.ts")
    assert 'id: "Orbit";' in out
    assert 'pattern?: "Circle" | "Race-Track";' in out
    assert "type AnyTask = Sample.Orbit | Sample.Hold;" in out


@pytest.mark.skipif(TSC is None, reason="no tsc (npm --prefix packages/typescript ci)")
def test_typescript_literal_ids_discriminate(tmp_path: Path) -> None:
    """A wrong-cased id is a type error against the real DcsTask.AnyTask."""
    api = tmp_path / "api.d.ts"
    merged, _ = merge_tree(str(REPO / "dcs-world-schema"))
    export_typescript.export_to_typescript(json.loads(json.dumps(merged)), str(api))
    (tmp_path / "check.ts").write_text(
        'export const good: DcsTask.AnyTask = { id: "Orbit" };\n'
        "// @ts-expect-error DCS casing only\n"
        'export const bad: DcsTask.AnyTask = { id: "orbit", params: {} };\n',
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "strict": True,
                    "noEmit": True,
                    "module": "commonjs",
                },
                "files": ["api.d.ts", "check.ts"],
            }
        ),
        encoding="utf-8",
    )
    run = subprocess.run(
        [str(TSC), "-p", str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stdout + run.stderr


def test_lua_literal_types(tmp_path: Path) -> None:
    out = _export(export_lua.export_to_lua, LITERAL, tmp_path / "a.lua")
    assert '---@field id "Orbit"' in out
    assert '---@field pattern? "Circle"|"Race-Track"' in out
    assert "---@alias Sample.AnyTask Sample.Hold|Sample.Orbit" in out


def test_go_literal_types(tmp_path: Path) -> None:
    out = _export(export_golang.export_to_golang, LITERAL, tmp_path / "a.go")
    assert '\tId string `json:"id"`' in out
    assert '\tPattern *string `json:"pattern,omitempty"`' in out
    assert 'const SampleOrbit_Id = "Orbit"' in out
    assert 'const SampleOrbit_Pattern_Race_Track = "Race-Track"' in out
    assert "type SampleAnyTask = interface{}" in out


def test_python_literal_types(tmp_path: Path) -> None:
    path = tmp_path / "literal_api.py"
    _export(export_python.export_to_python, LITERAL, path)
    mod = _import(path, "literal_api")
    hints = typing.get_type_hints(mod.Sample_Orbit, vars(mod))
    assert hints["id"] == typing.Literal["Orbit"]
    assert typing.get_args(mod.Sample_AnyTask) == (
        typing.ForwardRef("Sample_Orbit"),
        typing.ForwardRef("Sample_Hold"),
    )


OPEN: dict[str, Any] = {
    "globals": {},
    "types": {
        "Sample.Kind": {
            "kind": "enum",
            "description": "Kinds.",
            "values": {"Big": "big", "Small": "small"},
        },
        "Sample.Pick": {
            "kind": "record",
            "fields": {
                "kind": {"type": "Sample.Kind | string"},
                "size": {"type": '"S" | number | "L"'},
            },
            "required": ["kind", "size"],
        },
    },
}


def test_typescript_open_string_keeps_literals(tmp_path: Path) -> None:
    out = _export(export_typescript.export_to_typescript, OPEN, tmp_path / "a.d.ts")
    assert "kind: Sample.Kind | (string & {});" in out


def test_python_literal_union_is_one_literal(tmp_path: Path) -> None:
    path = tmp_path / "open_api.py"
    _export(export_python.export_to_python, OPEN, path)
    assert 'size: Literal["S", "L"] | float' in path.read_text(encoding="utf-8")
    mod = _import(path, "open_api")
    hints = typing.get_type_hints(mod.Sample_Pick, vars(mod))
    assert typing.get_args(hints["size"])[0] == typing.Literal["S", "L"]


def test_lua_output_suits_luals(built: Any) -> None:
    """No ``---@version`` (LuaLS: deprecated), no redefined builtin
    ``unknown``, function tables under a global as classes."""
    lua = built["lua"]
    assert "@version" not in lua and "--- Since DCS 1.2.0.\n" in lua
    assert "---@alias unknown" not in lua
    assert "---@field action trigger.action " in lua
    assert "---@class trigger.action\ntrigger.action = trigger.action or {}\n" in lua
    assert "\nfunction trigger.action.smoke(point, color) end\n" in lua
    assert "fun(...)" not in lua


def test_literal_types_elsewhere() -> None:
    args = export_selene_yaml.build_function_args([{"name": "id", "type": '"Orbit"'}])
    assert args == [{"type": "string"}]
    types = {
        "Entity.Thing": {
            "kind": "record",
            "fields": {"shape": {"type": '"box" | nil'}},
            "required": [],
        }
    }
    thing = export_jsonschema.export(types)["definitions"]["Entity.Thing"]
    assert thing["properties"]["shape"]["anyOf"] == [
        {"type": "string", "const": "box"},
        {"type": "null"},
    ]


# --- Entity types ----------------------------------------------------------


ENTITY_SPEC: dict[str, Any] = {
    "globals": {},
    "types": {
        **SAMPLE["types"],
        "Entity.Thing": {
            "kind": "record",
            "fields": {"kind": {"type": "Entity.ThingKind"}},
        },
        "Entity.ThingKind": {"kind": "enum", "values": {"A": "a"}},
    },
}


@pytest.mark.parametrize(
    ("fn", "name"),
    [
        (export_typescript.export_to_typescript, "a.d.ts"),
        (export_lua.export_to_lua, "a.lua"),
        (export_golang.export_to_golang, "a.go"),
        (export_python.export_to_python, "a.py"),
    ],
)
def test_entity_types_are_left_out(
    fn: Callable[..., None], name: str, tmp_path: Path
) -> None:
    out = _export(fn, ENTITY_SPEC, tmp_path / name)
    assert "Thing" not in out
    assert "Aircraft" in out


def test_selene_leaves_out_entity_types(spec: dict[str, Any]) -> None:
    names = export_selene_yaml.export_to_selene_yaml(spec)["globals"]
    assert names and not [n for n in names if n.startswith("Entity.")]


# --- DcsDb and type-only namespaces ----------------------------------------

# Roots of type-only types in the real spec (no such DCS global).
TYPE_ONLY_ROOTS = ("DcsTask", "MarkupLineType", "DcsId")


@pytest.fixture(scope="module")
def built(spec: dict[str, Any], tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The API outputs of the real spec, by language."""
    tmp = tmp_path_factory.mktemp("api")
    out: dict[str, Any] = {
        lang: _export(fn, spec, tmp / name)
        for lang, fn, name in (
            ("lua", export_lua.export_to_lua, "a.lua"),
            ("ts", export_typescript.export_to_typescript, "a.d.ts"),
            ("go", export_golang.export_to_golang, "a.go"),
            ("py", export_python.export_to_python, "a.py"),
        )
    }
    out["selene"] = export_selene_yaml.export_to_selene_yaml(copy.deepcopy(spec))
    return out


def test_spec_has_the_types_the_outputs_leave_out(spec: dict[str, Any]) -> None:
    types = spec["types"]
    assert any(n.startswith(DCS_DB_PREFIX) for n in types)
    for root in TYPE_ONLY_ROOTS:
        assert any(n.split(".")[0] == root for n in types), root
        assert is_type_only(root, runtime_roots(spec))


@pytest.mark.parametrize("lang", ["lua", "ts", "go", "py"])
def test_outputs_leave_out_dcs_db(built: Any, lang: str) -> None:
    assert "DcsDb" not in built[lang]
    assert "DcsTask" in built[lang]  # the task types stay, as types


def test_selene_declares_no_type_only_globals(built: Any) -> None:
    names = built["selene"]["globals"]
    roots = {n.split(".")[0] for n in names}
    assert not roots & {"DcsDb", *TYPE_ONLY_ROOTS}
    for name in ("AI.Option.Air.id.ROE", "country.id.USA", "trigger.action.outText"):
        assert name in names, name


def test_lua_has_no_tables_for_type_only_namespaces(built: Any) -> None:
    lua = built["lua"]
    assigned = set(re.findall(r"^([A-Za-z_][\w.]*)\s*=", lua, re.MULTILINE))
    assert not {n for n in assigned if n.split(".")[0] in TYPE_ONLY_ROOTS}
    assert not re.search(r"^---@enum (DcsTask|MarkupLineType)\b", lua, re.MULTILINE)
    assert "---@alias DcsTask.OptionName\n---| -1 # NO_OPTION\n" in lua
    assert "---@alias MarkupLineType\n---| 0 # NoLine\n" in lua
    assert "---@class DcsTask.Task.Orbit\n" in lua
    # real DCS tables keep theirs
    for name in ("AI.Option", "AI.Option.Air.id", "country.id", "trigger"):
        assert name in assigned, name
    assert "---@enum AI.Option.Air.id\n" in lua and "---@enum country.id\n" in lua


def test_typescript_type_only_namespaces_hold_only_types(built: Any) -> None:
    ts = built["ts"]
    task_ns = ts[ts.index("declare namespace DcsTask {") :]
    task_ns = task_ns[: task_ns.index("\n}\n")]
    assert not re.search(r"^\s*(enum|const|let|var|function|class) ", task_ns, re.M)
    assert "type OptionName =\n        | -1 // NO_OPTION\n" in task_ns
    assert not re.search(r"^declare (enum|const) MarkupLineType\b", ts, re.MULTILINE)
    assert "declare type MarkupLineType =\n    | 0 // NoLine\n" in ts
    # real DCS enums stay values
    assert re.search(r"^\s*enum id \{", ts, re.MULTILINE)  # AI.Option.*.id, country.id


def test_type_roots_match_the_dumps_globals(spec: dict[str, Any]) -> None:
    """The globals the spec has only types under are DCS globals in the API
    dump's scripting env, and no type-only root is one."""
    dump = REPO / "dcs-world-reference" / "latest" / "api" / "scripting.json"
    dcs = set(json.loads(dump.read_text(encoding="utf-8"))["globals"])
    assert dcs >= TYPE_ROOT_GLOBALS
    type_roots = {n.split(".")[0] for n in api_spec(spec)["types"]}
    assert sorted((type_roots - runtime_roots(spec)) & dcs) == []


def test_merged_schema_leaves_out_dcs_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "schema.json"
    root = str(REPO / "dcs-world-schema")
    monkeypatch.setattr(sys, "argv", ["merge", str(out), "--root", root])
    merge.main()
    types = json.loads(out.read_text(encoding="utf-8"))["types"]
    assert "DcsTask.OptionName" in types and "country.id" in types
    assert not [n for n in types if n.startswith(DCS_DB_PREFIX)]


# --- helpers ---------------------------------------------------------------


def _optional(record: dict[str, Any], field: str) -> bool:
    _, nullable = strip_null(parse_type(record["fields"][field]["type"]))
    return nullable or field not in (record.get("required") or [])


def _assert_fields_rendered(
    out: str,
    spec: dict[str, Any],
    name: str,
    *,
    start: str,
    line: Callable[[str, bool], str],
) -> None:
    """Each field of ``name`` appears in its rendered block, ``?`` iff optional."""
    record = spec["types"][name]
    assert record["kind"] == "record" and record["fields"]
    block = out[out.index(start) :]
    if "{" in start:  # TypeScript: up to the closing brace
        block = block[: block.index("}")]
    else:  # EmmyLua: the run of ``---@`` annotation lines
        lines = block.splitlines()
        block = "\n".join(
            lines[: next(i for i, ln in enumerate(lines) if not ln.startswith("---@"))]
        )
    for field in record["fields"]:
        assert line(field, _optional(record, field)) in block, (name, field)
