"""Probe results in the generated env globals and in verify."""

from typing import Any

from tools import verify
from tools.datamine import api_schema

VERSION = "9.9.9.7"


def _fn(what: str = "C") -> dict[str, Any]:
    return {"type": "function", "what": what}


def _dump(globals_: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "dcs-api-dump/2",
        "env": "hooks",
        "dcsVersion": VERSION,
        "status": "ok",
        "globals": globals_,
    }


def _table(members: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "table",
        "members": [
            {"key": k, "keyType": "string", "value": v} for k, v in members.items()
        ],
    }


PROBE = {
    "dcsVersion": VERSION,
    "envs": {
        "hooks": {
            "DCS.get": {
                "status": "ok",
                "what": "C",
                "conclusive": True,
                "minArgs": 1,
                "params": [{"position": 1, "from": "error", "expected": "string"}],
                "returns": [{"type": "number"}],
            },
            "DCS.alias": {"status": "sameAs", "sameAs": "DCS.get"},
            "DCS.boom": {"status": "crashed", "what": "C"},
            "DCS.half": {
                "status": "error",
                "what": "C",
                "params": [{"position": 1, "from": "error", "expected": "number"}],
            },
            "free": {"status": "ok", "what": "C", "conclusive": True, "minArgs": 0},
        }
    },
}


def test_generated_env_uses_the_probe() -> None:
    dump = _dump(
        {
            "DCS": _table(
                {"get": _fn(), "alias": _fn(), "boom": _fn(), "half": _fn(), "x": _fn()}
            ),
            "free": _fn(),
        }
    )
    files = api_schema.generate_env(dump, PROBE)
    dcs = files["DCS.generated.yaml"]
    assert "Signature probed (DCS 9.9.9.7)" in dcs
    assert "- name: param1\n          type: string\n        returns: number" in dcs
    assert dcs.count("Signature probed") == 2  # get and its alias
    flat = " ".join(dcs.split())  # descriptions wrap at the YAML width
    assert "Crashed or hung DCS on invalid arguments (DCS 9.9.9.7)." in flat
    assert "Probe (DCS 9.9.9.7): argument 1 must be a number." in flat
    assert "      x:\n        type: function\n" in dcs
    free = files["_G.generated.yaml"]
    assert "Signature probed" in free and "params: []\n        returns: void" in free
    # Without a probe (or of another DCS version) nothing changes.
    plain = api_schema.generate_env(dump)
    assert "probe" not in plain["DCS.generated.yaml"].lower()


def test_generated_env_uses_a_carried_probe_labelled() -> None:
    carried = {**PROBE, "dcsVersion": VERSION, "probedOn": "9.9.8.1"}
    # get is a Lua function in this version: its C probe record does not apply.
    dump = _dump({"DCS": _table({"get": _fn("Lua"), "half": _fn()}), "free": _fn()})
    files = api_schema.generate_env(dump, carried)
    dcs = " ".join(files["DCS.generated.yaml"].split())
    assert "Signature probed" not in dcs
    assert "Probe (DCS 9.9.8.1): argument 1 must be a number." in dcs
    assert "Signature probed (DCS 9.9.8.1)" in files["_G.generated.yaml"]
    assert "Signature probed (DCS 9.9.9.7)" not in files["_G.generated.yaml"]


def test_verify_reports_probe_disagreements() -> None:
    schema = {
        "globals": {
            "Object": {
                "kind": "class",
                "instance": {
                    "getName": {"params": [], "returns": "string"},
                },
            },
            "Unit": {"kind": "class", "inherits": ["Object"], "instance": {}},
            "trigger": {
                "kind": "singleton",
                "static": {
                    "action": {
                        "type": "table",
                        "static": {
                            "out": {
                                "params": [
                                    {"name": "text", "type": "string"},
                                    {"name": "time", "type": "integer"},
                                    {
                                        "name": "clear",
                                        "type": "boolean",
                                        "optional": True,
                                    },
                                ],
                                "returns": "void",
                            },
                            "odd": {
                                "description": "Present; signature not documented.",
                                "returns": "any",
                            },
                        },
                    }
                },
            },
        }
    }
    self_ = {"position": 1, "from": "self", "sample": "Unit"}
    probe = {
        "envs": {
            "scripting": {
                "Unit.getName": {
                    "conclusive": True,
                    "minArgs": 1,
                    "params": [self_],
                    "returns": [{"type": "number"}, {"type": "string"}],
                },
                "trigger.action.out": {
                    "conclusive": True,
                    "minArgs": 2,
                    "params": [
                        {"position": 1, "from": "error", "expected": "number"},
                        {"position": 2, "from": "error", "expected": "number"},
                    ],
                },
                "trigger.action.odd": {"conclusive": True, "minArgs": 3},
                "Unit.gone": {"conclusive": True, "minArgs": 0},
            }
        }
    }
    assert verify.probe_disagreements(schema, probe) == [
        "Unit.getName (method): returned 2 value(s), documented 1; "
        "return 1: DCS returned number, documented string",
        "trigger.action.out (function): argument 1 (text): DCS expects number, "
        "documented string",
    ]


def test_verify_reports_enum_value_drift() -> None:
    api = {
        "AI": {
            "kind": "table",
            "members": [
                {
                    "name": "Skill",
                    "type": "table",
                    "sub": {
                        "kind": "table",
                        "members": [
                            {"name": "GOOD", "type": "string", "value": "Good"},
                            {"name": "HIGH", "type": "string", "value": "High"},
                        ],
                    },
                }
            ],
        }
    }
    schema = {
        "types": {
            "AI.Skill": {"kind": "enum", "values": {"GOOD": "GOOD", "HIGH": "High"}},
            "AI.Other": {"kind": "enum", "values": {"X": 1}},
        }
    }
    assert verify.enum_value_drift(schema, api) == [
        "AI.Skill.GOOD: schema 'GOOD', DCS 'Good'"
    ]
