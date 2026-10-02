"""Go identifiers and generated union types of the Go package emitter."""

from __future__ import annotations

import gzip
from typing import Any

import pytest

from tools.package import entity_types
from tools.package.go_package import Emitter, go_name, gz, union_go, union_name


def test_gz_is_reproducible() -> None:
    data = b'{"a": 1}' * 100
    assert gz(data) == gz(data)
    assert gzip.decompress(gz(data)) == data
    # mtime 0 and no FNAME flag: the header is fixed.
    assert gz(data)[3:8] == b"\x00\x00\x00\x00\x00"


@pytest.mark.parametrize(
    ("name", "ident"),
    [
        ("beaconId", "BeaconID"),
        ("gun_ammo", "GunAmmo"),
        ("country.id", "CountryID"),
        ("BEACON_TYPE_VOR", "BeaconTypeVOR"),
        ("wsType_Radar_Miss", "WsTypeRadarMiss"),
        ("NEW ZEALAND", "NewZealand"),
        ("clsid", "CLSID"),
        ("ILSFreq", "ILSFreq"),
        ("dcsVersion", "DCSVersion"),
    ],
)
def test_go_name(name: str, ident: str) -> None:
    assert go_name(name) == ident


NUMBER = {"type": "number"}
STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}


def _emitter(fields: dict[str, Any], extra: dict[str, Any] | None = None) -> Emitter:
    """An emitter over a record ``Entity.R`` with ``fields`` (all required),
    an int enum ``Entity.E`` and the ``extra`` definitions."""
    schema = {
        "definitions": {
            "Entity.E": {"enum": [1, 2], "x-values": {"A": 1, "B": 2}},
            "Entity.R": {
                "type": "object",
                "properties": fields,
                "required": list(fields),
            },
            **(extra or {}),
        }
    }
    return Emitter(entity_types.definitions(schema, {"types": {}}))


def _any_of(*branches: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": list(branches)}


def test_unions_are_generated_per_primitive_set() -> None:
    emitter = _emitter(
        {
            "a": _any_of(NUMBER, STRING),
            "b": _any_of(BOOLEAN, NUMBER),
            "c": _any_of(BOOLEAN, NUMBER, STRING),
            "d": _any_of(STRING, NUMBER),
            "e": _any_of({"$ref": "#/definitions/Entity.E"}, NUMBER),
        }
    )
    out = emitter.types()
    assert '\tA NumberOrString `json:"a"`' in out
    assert '\tB BoolOrNumber `json:"b"`' in out
    assert '\tC Scalar `json:"c"`' in out
    assert '\tD NumberOrString `json:"d"`' in out
    assert '\tE float64 `json:"e"`' in out  # numbers only: no union type
    assert out.count("type NumberOrString struct") == 1
    assert '"encoding/json"' in out
    assert sorted(union_name(p) for p in emitter.unions) == [
        "BoolOrNumber",
        "NumberOrString",
        "Scalar",
    ]


def test_no_unions_no_imports() -> None:
    out = _emitter({"a": NUMBER}).types()
    assert "import" not in out


def test_union_decodes_only_its_member_kinds() -> None:
    source = "\n".join(union_go(frozenset({"number", "string"})))
    assert "Bool" not in source
    assert "c == 't'" not in source  # a boolean falls through to the error
    assert "c == '\"'" in source and "c == '-'" in source
    assert '"dcsref: want a number or a string, got %s"' in source


@pytest.mark.parametrize(
    "branches",
    [
        (STRING, {"type": "array", "items": STRING}),
        (NUMBER, {"type": "null"}),
        (NUMBER, {}),
    ],
)
def test_unrepresentable_unions_fail(branches: tuple[dict[str, Any], ...]) -> None:
    with pytest.raises(ValueError, match="unsupported union"):
        _emitter({"a": _any_of(*branches)}).types()


def test_union_of_records_fails() -> None:
    record = {"type": "object", "properties": {}, "required": []}
    emitter = _emitter(
        {
            "a": _any_of(
                {"$ref": "#/definitions/Entity.P"}, {"$ref": "#/definitions/Entity.Q"}
            )
        },
        {"Entity.P": record, "Entity.Q": record},
    )
    with pytest.raises(ValueError, match="unsupported union"):
        emitter.types()
