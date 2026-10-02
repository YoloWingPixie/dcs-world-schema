"""The entity JSON Schema's annotations, per-series editor schemas and the
committed VS Code mapping."""

import json

import fastjsonschema
from conftest import entity_schema

from tools.datamine.common import LATEST, REFERENCE_DATA_DIR, REPO_ROOT, SERIES
from tools.export_jsonschema import editor_schemas, vscode_settings


def test_descriptions_and_titles() -> None:
    defs = entity_schema()["definitions"]
    store = defs["Entity.Store"]
    assert store["title"] == "Entity.Store"
    assert store["description"].startswith("A loadable store")
    assert store["properties"]["clsid"]["description"] == "Unique store CLSID."
    rack = store["properties"]["rack"]
    assert rack["x-ref"] == ["Entity.Rack"] and "description" in rack
    assert "description" in defs["Entity.Airbase"]["properties"]["stands"]


def test_editor_schemas_validate_a_record() -> None:
    schemas = editor_schemas(entity_schema())
    assert set(schemas) == {*SERIES, "manifest"}
    record = json.loads(
        (REFERENCE_DATA_DIR / LATEST / "aircraft" / "F-16C_50.json").read_text("utf-8")
    )
    fastjsonschema.compile(schemas["aircraft"])(record)
    assert "Entity.Aircraft" in schemas["aircraft"]["title"]


def test_vscode_settings_are_in_sync() -> None:
    committed = json.loads((REPO_ROOT / ".vscode" / "settings.json").read_text("utf-8"))
    assert committed == vscode_settings(), "run `task vscode:schemas`"
    matches = {e["url"]: e["fileMatch"] for e in committed["json.schemas"]}
    assert matches["./dist/schemas/airbases.schema.json"] == [
        "**/dcs-world-reference/*/airbases/*/*.json"
    ]
