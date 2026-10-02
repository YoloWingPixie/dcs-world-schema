from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tools.datamine.common import SERIES
from tools.package import build, bundles, entity_types
from tools.package.lua_data import lua_bundle, lua_key, lua_string

LUA = shutil.which("lua5.1") or shutil.which("luajit")

SCHEMA = {
    "definitions": {
        "Entity.Thing": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "kind": {"$ref": "#/definitions/Entity.Kind"},
                "shape": {"type": "string", "const": "box"},
                "from": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "tags": {"type": "array", "items": {"type": "string"}},
                "_source": {},
            },
            "required": ["id", "kind"],
            "additionalProperties": False,
        },
        "Entity.Kind": {"enum": [1, 2], "x-values": {"ONE": 1, "TWO": 2}},
        "country.id": {"enum": [0, 2]},
    }
}
SPEC = {"types": {"Entity.Thing": {"description": "A thing.", "fields": {}}}}


def test_type_names() -> None:
    assert entity_types.type_name("Entity.GunAmmo") == "GunAmmo"
    assert entity_types.type_name("country.id") == "CountryId"


def test_typescript_types() -> None:
    ts = entity_types.typescript(entity_types.definitions(SCHEMA, SPEC))
    assert "export type Kind = 1 | 2;" in ts
    assert "  ONE: 1," in ts
    assert "  id: string;" in ts
    assert '  shape?: "box";' in ts
    assert "  kind: Kind;" in ts
    assert "  from?: number | null;" in ts
    assert "  tags?: Array<string>;" in ts
    assert "  _source?: Record<string, string>;" in ts


def test_python_types_load() -> None:
    source = entity_types.python(entity_types.definitions(SCHEMA, SPEC))
    namespace: dict[str, Any] = {}
    exec(compile(source, "entities.py", "exec"), namespace)
    thing = namespace["Thing"]
    assert thing.__required_keys__ == {"id", "kind"}
    assert thing.__optional_keys__ == {"from", "tags", "shape", "_source"}
    assert '"shape": NotRequired[Literal["box"]]' in source
    assert namespace["KindValues"] == {"ONE": 1, "TWO": 2}


def test_emmylua_types() -> None:
    lua = entity_types.emmylua(entity_types.definitions(SCHEMA, SPEC))
    assert "---@alias Entity.Kind 1|2" in lua
    assert "---@field kind Entity.Kind" in lua
    assert "---@field from? number|nil" in lua
    assert '---@field shape? "box"' in lua


def test_missing_series_fails(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "manifest.json").write_text("{}")
    with pytest.raises(SystemExit):
        bundles.build(data, tmp_path / "out")


def test_lua_escapes() -> None:
    assert lua_string('a"b\\c\n\x01\x7fé') == '"a\\"b\\\\c\\n\\001\\127é"'
    assert lua_key("end") == '["end"]'
    assert lua_key("ok_1") == "ok_1"
    assert lua_key("1x") == '["1x"]'


@pytest.mark.skipif(LUA is None, reason="lua5.1/luajit not installed")
def test_lua_bundle_loads(tmp_path: Path) -> None:
    bundle = {"a\n]]": {"n": 0.1, "end": [True, "x\x00y"], "e": {}}, "2": {"n": 1e300}}
    path = tmp_path / "b.lua"
    path.write_text(lua_bundle(bundle, "test"), encoding="utf-8")
    check = (
        f't = dofile("{path.as_posix()}")\n'
        'r = t["a\\n]]"]\n'
        'assert(r.n == 0.1 and r["end"][1] == true and r["end"][2] == "x\\0y")\n'
        'assert(next(r.e) == nil and t["2"].n == 1e300)\n'
    )
    result = subprocess.run([str(LUA), "-e", check], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_bundle_keys() -> None:
    records = {name: {"id": f"x/{name}"} for name in ("b", "a")}
    out = bundles.build_bundle(SERIES["liveries"], records)
    assert list(out) == ["x/a", "x/b"]


def test_bundle_duplicate_key_fails() -> None:
    records = {name: {"id": "same"} for name in ("a", "b")}
    with pytest.raises(SystemExit):
        bundles.build_bundle(SERIES["aircraft"], records)


PYPROJECT = """[project]
name = "x"
version = "0.1.0"
description = "Typed data (DCS 2.9.1.1)"
keywords = ["dcs", "dcs-2.9.1.1"]
readme = "README.md"

[tool.x]
version = "keep"
"""


def test_package_json_sync() -> None:
    text = (
        '{"name": "x", "version": "0.1.0", "dcsVersion": "2.9.1.1", "type": "module"}'
    )
    out = build.package_json(text, "0.2.0", "2.9.29.27468")
    assert list(json.loads(out).items()) == [
        ("name", "x"),
        ("version", "0.2.0"),
        ("dcsVersion", "2.9.29.27468"),
        ("type", "module"),
    ]
    assert build.package_json(out, "0.2.0", "2.9.29.27468") == out


def test_package_lock_sync() -> None:
    lock = {
        "name": "x",
        "version": "0.1.0",
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "x", "version": "0.1.0"},
            "node_modules/typescript": {"version": "7.0.2"},
        },
    }
    out = build.package_lock(json.dumps(lock), "0.2.0", "2.9.29.27468")
    got = json.loads(out)
    assert list(got) == list(lock)
    assert got["version"] == got["packages"][""]["version"] == "0.2.0"
    assert got["packages"]["node_modules/typescript"]["version"] == "7.0.2"
    assert build.package_lock(out, "0.2.0", "2.9.29.27468") == out
    with pytest.raises(SystemExit):
        build.package_lock('{"version": "0.1.0"}', "0.2.0", "2.9.29.27468")


def test_pyproject_sync() -> None:
    out = build.pyproject(PYPROJECT, "0.2.0", "2.9.29.27468")
    doc = tomllib.loads(out)
    assert doc["project"]["version"] == "0.2.0"
    assert doc["project"]["description"] == "Typed data (DCS 2.9.29.27468)"
    assert doc["project"]["keywords"] == ["dcs", "dcs-2.9.29.27468"]
    assert doc["tool"]["x"]["version"] == "keep"
    assert build.pyproject(out, "0.2.0", "2.9.29.27468") == out


def test_pyproject_without_keywords_fails() -> None:
    text = PYPROJECT.replace('keywords = ["dcs", "dcs-2.9.1.1"]\n', "")
    with pytest.raises(SystemExit):
        build.pyproject(text, "0.2.0", "2.9.29.27468")


def test_lua_zip_name() -> None:
    name = build.lua_zip_name("0.3.5", "2.9.29.27468")
    assert name == "dcs-world-reference-lua-0.3.5-dcs2.9.29.27468.zip"
