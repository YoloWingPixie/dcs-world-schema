"""The Mission Editor action extraction (me-action-db.lua, action_sources,
mission_corpus, extract_actions) and the generated DcsTask types
(action_types), on stand-in Mission Editor modules and missions. The loader
and luac tests are skipped without lua5.1/luac5.1."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from conftest import entity_schema, write

from tools.datamine import (
    action_sources,
    action_types,
    extract_actions,
    mission_corpus,
    overlays,
)
from tools.datamine.common import generated_drift

LUA = shutil.which("lua5.1")
LUAC = shutil.which("luac5.1")
needs_lua = pytest.mark.skipif(
    LUA is None or LUAC is None, reason="lua5.1/luac5.1 not installed"
)

ACTION_DB = """\
local base = _G

module('me_action_db')

local require = base.require
local U = require('me_utilities')
local DB = require('me_db_api')
local mission = require('me_mission')
local OptionsData = require('Options.Data')
local mod_dictionary = require('dictionary')
local TriggerZoneController = require('Mission.TriggerZoneController')
local ProductType = require('me_ProductType')

require('i18n').setup(_M)

weaponTable = { noWeapon = { name = _('No weapon'), value = 0 } }

ActionType = { TASK = 1, ENROUTE_TASK = 2, COMMAND = 3, OPTION = 4 }
ActionId = { NO_TASK = 1, ORBIT = 2, CAP = 3, INVISIBLE = 4, ROE = 5, FORMATION = 6 }

actionTypeData = {
	[ActionType.TASK] = { displayName = _('Perform Task'), defaultActionId = ActionId.NO_TASK },
}

local function makeWrappedAction(id, params)
\treturn { id = 'WrappedAction', params = { action = { id = id, params = params or {} } } }
end

local function declareCommand(id, displayName, desc, params, verify, makeParams)
\treturn { type = ActionType.COMMAND, displayName = displayName, desc = desc,
\t\tverifyGroupCapability = verify, makeParams = makeParams, task = makeWrappedAction(id, params) }
end

local OptionName = { NO_OPTION = -1, ROE = 0, FORMATION = 5, AWARNESS_LEVEL = 11 }

optionValues = {
\t[OptionName.ROE] = {
\t\t['plane'] = { list = { 0, 4 }, default = 4 },
\t\t['vehicle'] = { list = { 0, 4 }, default = 4 },
\t\t['ship'] = { list = { 0 }, default = 0 },
\t},
\t[OptionName.AWARNESS_LEVEL] = { units = U.timeUnits, min = 0, max = 10, default = 1 },
}
optionValueDisplayName = { [OptionName.ROE] = { [0] = _('WEAPON FREE'), [4] = _('WEAPON HOLD') } }

do
\toptionValues[OptionName.FORMATION] = { ['plane'] = { list = {}, default = DB.db.Formations['plane'].default } }
\toptionValueDisplayName[OptionName.FORMATION] = {}
\tfor groupType, formations in base.pairs(DB.db.Formations) do
\t\tfor _, f in base.pairs(formations.list) do
\t\t\tbase.table.insert(optionValues[OptionName.FORMATION][groupType].list, f.WorldID)
\t\t\toptionValueDisplayName[OptionName.FORMATION][f.WorldID] = f.Name
\t\tend
\tend
end

local function isRefuelable(group)
\tif DB.findAttribute(group.attribute, "Refuelable") then return nil end
\treturn _("has no aerial refueling capabilities")
end

function getNewParams(group)
\treturn { groupId = 1, extra = true }
end

AerobaticsManeuversData = {
\t['LOOP'] = { displayName = _('Loop'), param = { FlightTime = { value = 10, min_v = 1, order = 6 } } },
}

actionsData = {
\t[ActionId.NO_TASK] = { type = ActionType.TASK, displayName = _('No Task'), desc = _('Empty task'), task = { id = 'NoTask', params = {} } },
\t[ActionId.ORBIT] = {
\t\ttype = ActionType.TASK,
\t\tdisplayName = _('Orbit'),
\t\tdesc = _('Fly orbit'),
\t\tverifyGroupCapability = isRefuelable,
\t\ttask = {
\t\t\tid = 'Orbit',
\t\t\tparams = {
\t\t\t\tpattern = nil, -- set by the panel
\t\t\t\taltitude = 2000,
\t\t\t}
\t\t}
\t},
\t[ActionId.CAP] = { type = ActionType.ENROUTE_TASK, displayName = _('CAP'), task = { id = 'EngageTargets', key = 'CAP', params = { targetTypes = { 'Air' }, priority = 0 } } },
\t[ActionId.INVISIBLE] = declareCommand('SetInvisible', _('Invisible'), _('Hide the group'), { value = true },
\t\tfunction(group)
\t\t\tif DB.findAttribute(group.attribute, 'Ships') then return _('no ships') end
\t\tend,
\t\tgetNewParams),
\t[ActionId.ROE] = { type = ActionType.OPTION, displayName = _('ROE'), task = makeWrappedAction('Option', { name = OptionName.ROE }) },
\t[ActionId.FORMATION] = { type = ActionType.OPTION, displayName = _('Formation'), task = makeWrappedAction('Option', { name = OptionName.FORMATION }) },
}

availableActions = {
\tplane = {
\t\t[ActionType.TASK] = { Default = { ActionId.NO_TASK, ActionId.ORBIT }, CAP = { ActionId.NO_TASK, ActionId.ORBIT } },
\t\t[ActionType.ENROUTE_TASK] = { CAP = { ActionId.CAP } },
\t\t[ActionType.COMMAND] = { Default = { ActionId.INVISIBLE } },
\t\t[ActionType.OPTION] = { Default = { ActionId.ROE, ActionId.AWARNESS_LEVEL, ActionId.FORMATION } },
\t},
\tvehicle = {
\t\t[ActionType.COMMAND] = { Default = { ActionId.INVISIBLE } },
\t\t[ActionType.OPTION] = { Default = { ActionId.ROE } },
\t},
}

if base.ED_PUBLIC_AVAILABLE then
\tavailableActions.plane[ActionType.TASK].CAP = nil
end
"""

STATIC_DB = """\
local base = _G

module('me_staticAction_db')

local require = base.require
local DB = require('me_db_api')

require('i18n').setup(_M)

ActionType = { TASK = 1 }
ActionId = { NO_TASK = "NO_TASK", FARP_SPAWN = "FARP_SPAWN" }

actionsData = {
\t[ActionId.NO_TASK] = { type = ActionType.TASK, displayName = _('No Task'), desc = _('Empty task'), task = { id = 'NoTask', params = {} } },
\t[ActionId.FARP_SPAWN] = { type = ActionType.TASK, displayName = _('Farp spawn'),
\t\ttask = { id = 'FarpSpawn', params = { preset = 1 } },
\t\tverifyUnitCapability = function(unit) return _("has no cargo") end },
}

availableActions = { Default = { ActionId.NO_TASK, ActionId.FARP_SPAWN } }
"""

EDIT_PANEL = """\
local actionDB = require('me_action_db')
local actionParamPanels = require('me_action_param_panels')

local function create()
\tlocal function orbitExtras(data)
\t\treturn data.actionParams.clockWise
\tend

\tparamPanelConstructors = {
\t\t[actionDB.ActionId.ORBIT] = function()
\t\t\tlocal handler = {
\t\t\t\topen = function(self, data)
\t\t\t\t\torbitExtras(data)
\t\t\t\t\treturn data.actionParams.pattern
\t\t\t\tend,
\t\t\t}
\t\t\thandler.childs = { alt = actionParamPanels.Altitude:create(handler, 1) }
\t\t\treturn handler
\t\tend,
\t\t[actionDB.ActionId.INVISIBLE] = function()
\t\t\treturn { open = function(self, data) return data.actionParams.value end }
\t\tend,
\t}
end
"""

PARAM_PANELS = """\
local base = _G
module('me_action_param_panels')

do
\tAltitude = {
\t\topen = function(self, data)
\t\t\tself.data.actionParams.altitude = 1
\t\t\tSpeed:create(self, 2)
\t\tend,
\t}
end

do
\tSpeed = {
\t\topen = function(self, data)
\t\t\tdata.actionParams.speed = 2
\t\tend,
\t}
\tUnrelated = {
\t\topen = function(self, data)
\t\t\tdata.actionParams.nothing = 3
\t\tend,
\t}
end
"""

FORMATIONS = "return { plane = { list = { { WorldID = 3, Name = 'Wedge' }, { WorldID = 1, Name = 'Line' } } } }"

MISSION = """\
mission = {
  coalition = { blue = { country = { [1] = {
    plane = { group = { [1] = {
      route = { points = { [1] = { task = { id = 'ComboTask', params = { tasks = {
        [1] = { id = 'Orbit', params = { pattern = 'Circle', altitude = 100 } },
        [2] = { id = 'EngageTargets', key = 'CAP', params = { targetTypes = { 'Air' } } },
        [3] = { id = 'WrappedAction', params = { action = { id = 'Option', params = { name = 0, value = 4 } } } },
        [4] = { id = 'ControlledTask', params = { task = { id = 'WrappedAction',
                params = { action = { id = 'SetInvisible', params = { value = true } } } } } },
      } } } } } },
      tasks = { [1] = { id = 'orbit', params = {} } },
    } } },
  } } } },
}
"""


def _modules(root: Path) -> Path:
    d = root / "MissionEditor" / "modules"
    write(d / "me_action_db.lua", ACTION_DB)
    write(d / "me_staticAction_db.lua", STATIC_DB)
    write(d / "me_action_edit_panel.lua", EDIT_PANEL)
    write(d / "me_action_param_panels.lua", PARAM_PANELS)
    return d


def _miz(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mission", text)


# ---------------------------------------------------------------------------
# Source text
# ---------------------------------------------------------------------------


def test_declared_nil_keys_per_action() -> None:
    assert action_sources.declared(ACTION_DB) == {"ORBIT": ["pattern"]}


def test_constructor_keys_are_top_level_only() -> None:
    text = 'return { a = 1, b = f(x, y), c = { d = 2 }, e == 3, ["s"] = 4, g = "h, i = j" }'
    assert action_sources._constructor_keys(text, text.index("{")) == {
        "a",
        "b",
        "c",
        "g",
    }


SCRIPT = """\
function trigger.action.groupStopMoving(group)
\tlocal command = {
\t\tid = 'StopRoute',
\t\tparams = {
\t\t\tvalue = true -- a comment
\t\t}
\t}
\tgroup:getController():setCommand(command)
end

function attack(g, t)
\tg:getController():pushTask({ id = "Orbit", params = { altitude = 100, pattern = t:name(), x = 1.5 } })
\tg:getController():setTask(t)
\tg:getController():setTask({ params = {} })
end
"""


def test_script_actions_read_controller_tables() -> None:
    lines = SCRIPT.split("\n")
    ranges = {1: 9, 11: 15}
    assert lines[14] == "end"
    assert action_sources.script_actions(SCRIPT, ranges) == [
        action_sources.ScriptAction(
            "StopRoute",
            "setCommand",
            "trigger.action.groupStopMoving",
            {"value": ["boolean"]},
        ),
        action_sources.ScriptAction(
            "Orbit",
            "pushTask",
            "attack",
            {"altitude": ["number"], "pattern": [], "x": ["number"]},
        ),
    ]


def test_returned_and_capability_follow_one_call() -> None:
    text = "\n".join(
        [
            "function inner(group)",  # 1
            "  if DB.findAttribute(u.attribute, 'Tankers') then return { a = 1 } end",
            "  return { b = 2 } -- { c = 3 }",
            "end",
            "local wrap = function(group)",  # 5
            "  if not inner(group) then return _('has no TACAN') end",
            "  return { d = { e = 4 } }",
            "end",
        ]
    )
    src = action_sources.ModuleSource(text, {"inner": (1, 4)})
    assert src.returned(5, 8) == ["a", "b", "d"]
    assert src.capability(5, 8) == (["Tankers"], ["has no TACAN"])


@needs_lua
def test_panel_params_follow_functions_and_panels(tmp_path: Path) -> None:
    d = _modules(tmp_path)
    out = action_sources.panel_params(
        EDIT_PANEL,
        action_sources.function_ranges(d / "me_action_edit_panel.lua"),
        PARAM_PANELS,
        action_sources.function_ranges(d / "me_action_param_panels.lua"),
    )
    assert out == {
        "INVISIBLE": ["value"],
        "ORBIT": ["altitude", "clockWise", "pattern", "speed"],
    }


# ---------------------------------------------------------------------------
# Missions
# ---------------------------------------------------------------------------


def test_mission_corpus_keys_contexts_and_values(tmp_path: Path) -> None:
    _miz(tmp_path / "Mods" / "campaigns" / "C" / "one.miz", MISSION)
    _miz(tmp_path / "Mods" / "campaigns" / "C" / "broken.miz", "mission = {")
    c = mission_corpus.scan(tmp_path, workers=1)
    assert c.files == 2
    assert [p for p, _ in c.failed] == ["Mods/campaigns/C/broken.miz"]
    a = c.actions
    assert sorted(a) == ["CAP", "Option:0", "Orbit", "SetInvisible", "orbit"]
    assert dict(a["Orbit"]["contexts"]) == {"route>ComboTask": 1}
    assert dict(a["Orbit"]["params"]["pattern"]) == {"string": 1}
    assert dict(a["Orbit"]["strings"]["pattern"]) == {"Circle": 1}
    assert dict(a["SetInvisible"]["contexts"]) == {
        "route>ComboTask>ControlledTask>WrappedAction": 1
    }
    assert dict(a["orbit"]["contexts"]) == {"triggered": 1}
    assert dict(c.option_values["Option:0"]) == {"number:4": 1}
    assert dict(c.keyed) == {"EngageTargets/CAP": 1}


def test_mission_corpus_cache_follows_installed_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scan = mission_corpus.scan
    monkeypatch.setattr(mission_corpus, "scan", lambda d: scan(d, workers=1))
    _miz(tmp_path / "Mods" / "campaigns" / "C" / "one.miz", MISSION)
    cache = tmp_path / "cache.json"
    fresh = extract_actions.corpus(tmp_path, cache)

    def no_scan(*_args: Any, **_kwargs: Any) -> mission_corpus.Corpus:
        raise AssertionError("scanned despite a current cache")

    with monkeypatch.context() as m:
        m.setattr(mission_corpus, "scan", no_scan)
        cached = extract_actions.corpus(tmp_path, cache)
    assert extract_actions._corpus_json(cached) == extract_actions._corpus_json(fresh)
    (tmp_path / "Mods" / "aircraft" / "New").mkdir(parents=True)
    _miz(tmp_path / "Mods" / "aircraft" / "New" / "two.miz", MISSION)
    assert extract_actions.corpus(tmp_path, cache).files == 2


# ---------------------------------------------------------------------------
# Loader and records
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> dict[str, Any]:
    if LUA is None:
        pytest.skip("lua5.1 not installed")
    return extract_actions.load_db(_modules(tmp_path), FORMATIONS)


def test_loader_reads_tables_locals_and_functions(db: dict[str, Any]) -> None:
    assert db["optionNames"] == {
        "NO_OPTION": -1,
        "ROE": 0,
        "FORMATION": 5,
        "AWARNESS_LEVEL": 11,
    }
    assert db["actions"]["ORBIT"]["task"] == {
        "id": "Orbit",
        "params": {"altitude": 2000},
    }
    assert db["actions"]["ORBIT"]["verifyGroupCapability"]["name"] == "isRefuelable"
    inline = db["actions"]["INVISIBLE"]["verifyGroupCapability"]
    assert "name" not in inline and inline["line"] < inline["lastLine"]
    assert db["actions"]["INVISIBLE"]["makeParams"]["name"] == "getNewParams"
    assert db["optionValues"]["11"]["units"] == {"unitsTable": "timeUnits"}
    assert db["optionValues"]["5"]["plane"]["list"] == [3, 1]
    plane_opts = db["availableActions"]["plane"]["OPTION"]["Default"]
    assert plane_opts == {"names": ["ROE", "FORMATION"], "holes": 1}
    assert "CAP" in db["availableActions"]["plane"]["TASK"]
    assert "CAP" not in db["availableActionsEdPublic"]["plane"]["TASK"]
    assert set(db["static"]["actions"]) == {"NO_TASK", "FARP_SPAWN"}
    assert "getNewParams" in db["functions"]


def test_loader_fails_on_an_unstubbed_require(tmp_path: Path) -> None:
    if LUA is None:
        pytest.skip("lua5.1 not installed")
    d = _modules(tmp_path)
    write(
        d / "me_action_db.lua", "local x = require('me_new_dependency')\n" + ACTION_DB
    )
    with pytest.raises(SystemExit):
        extract_actions.load_db(d, FORMATIONS)


@needs_lua
def test_script_sources_scan_scripts_coremods_and_mods(tmp_path: Path) -> None:
    write(tmp_path / "Scripts/ScriptingSystem.lua", SCRIPT)
    write(tmp_path / "CoreMods/tech/x/readme.lua", "local a = 1\n")
    write(tmp_path / "Mods/tech/y/ai.lua", SCRIPT)
    found = extract_actions.script_sources(tmp_path)
    assert list(found) == ["Scripts/ScriptingSystem.lua", "Mods/tech/y/ai.lua"]
    assert found["Mods/tech/y/ai.lua"] == found["Scripts/ScriptingSystem.lua"]
    shutil.rmtree(tmp_path / "CoreMods")
    with pytest.raises(SystemExit):
        extract_actions.script_sources(tmp_path)


SCRIPTS = {
    "Scripts/ScriptingSystem.lua": action_sources.script_actions(SCRIPT, {1: 9, 11: 15})
}


def _records(
    db: dict[str, Any],
    corpus: mission_corpus.Corpus | None = None,
    scripts: dict[str, list[action_sources.ScriptAction]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    texts = {
        extract_actions.ACTION_DB: ACTION_DB,
        extract_actions.STATIC_DB: STATIC_DB,
    }
    panels = {"ORBIT": ["altitude", "pattern", "speed"]}
    actions, problems = extract_actions.build_actions(
        db, texts, panels, corpus, scripts
    )
    options, option_problems = extract_actions.build_options(db, actions, corpus)
    return actions, options, problems + option_problems


def test_script_actions_join_records(db: dict[str, Any]) -> None:
    actions, _, problems = _records(db, scripts=SCRIPTS)
    stop = actions["StopRoute"]
    assert stop["kind"] == "command" and stop["modules"] == []
    assert stop["wrapped"] is False and stop["availableFor"] == []
    assert "displayName" not in stop and "defaultParams" not in stop
    assert stop["params"] == [
        {"name": "value", "seenIn": ["scripts"], "types": ["boolean"]}
    ]
    assert stop["scripts"] == [
        {
            "file": "Scripts/ScriptingSystem.lua",
            "call": "setCommand",
            "function": "trigger.action.groupStopMoving",
        }
    ]
    orbit = actions["ORBIT"]
    assert orbit["scripts"][0]["call"] == "pushTask"
    params = {p["name"]: p for p in orbit["params"]}
    assert "scripts" in params["altitude"]["seenIn"]
    assert params["x"] == {"name": "x", "seenIn": ["scripts"], "types": ["number"]}
    assert not any("StopRoute" in p for p in problems)
    overlays.apply(_point_overlay(["ORBIT"]), {"actions": actions})
    schema = {**entity_schema(), "$ref": "#/definitions/Entity.Action"}
    for rec in (stop, orbit):
        jsonschema.validate(rec, schema)


def test_maneuvers_keep_dcs_param_fields() -> None:
    raw = {
        "LOOP": {
            "displayName": "Loop",
            "desc": "Vertical loop",
            "param": {"Alt": {"value": 500, "min_v": 100, "max_v": 1000, "order": 1}},
        },
        "HOLD": {"displayName": "Hold", "param": {}},
    }
    assert extract_actions._maneuvers(raw) == [
        {"id": "HOLD", "displayName": "Hold", "params": []},
        {
            "id": "LOOP",
            "displayName": "Loop",
            "description": "Vertical loop",
            "params": [
                {"name": "Alt", "max_v": 1000, "min_v": 100, "order": 1, "value": 500}
            ],
        },
    ]


def test_script_task_without_a_kind_fails(db: dict[str, Any]) -> None:
    uses = [action_sources.ScriptAction("NoSuchTask", "pushTask", None, {})]
    with pytest.raises(SystemExit):
        _records(db, scripts={"Scripts/x.lua": uses})


def test_action_records(db: dict[str, Any], tmp_path: Path) -> None:
    _miz(tmp_path / "m" / "one.miz", MISSION)
    corpus = mission_corpus.scan(tmp_path / "m", workers=1)
    actions, options, problems = _records(db, corpus)
    assert sorted(actions) == [
        "CAP",
        "FARP_SPAWN",
        "FORMATION",
        "INVISIBLE",
        "NO_TASK",
        "ORBIT",
        "ROE",
    ]
    orbit = actions["ORBIT"]
    assert (
        orbit["kind"] == "task" and orbit["dcsId"] == "Orbit" and not orbit["wrapped"]
    )
    assert orbit["capability"] == {
        "rule": "isRefuelable",
        "attributes": ["Refuelable"],
        "messages": ["has no aerial refueling capabilities"],
    }
    params = {p["name"]: p for p in orbit["params"]}
    assert params["pattern"]["seenIn"] == ["declared", "panel", "missions"]
    assert params["pattern"]["missionStrings"] == [{"value": "Circle", "count": 1}]
    assert params["altitude"]["types"] == ["number"]
    assert params["speed"] == {"name": "speed", "seenIn": ["panel"], "types": []}
    assert {"category": "plane", "groupTask": "CAP", "edPublicHidden": True} in orbit[
        "availableFor"
    ]
    assert actions["CAP"]["key"] == "CAP" and actions["CAP"]["kind"] == "enrouteTask"
    inv = actions["INVISIBLE"]
    assert inv["wrapped"] and inv["dcsId"] == "SetInvisible"
    assert inv["makeParams"] == {"rule": "getNewParams"}
    assert {p["name"] for p in inv["params"]} == {"extra", "groupId", "value"}
    assert inv["capability"] == {"attributes": ["Ships"], "messages": ["no ships"]}
    assert inv["missions"]["contexts"] == {
        "route>ComboTask>ControlledTask>WrappedAction": 1
    }
    assert actions["NO_TASK"]["modules"] == ["me_action_db", "me_staticAction_db"]
    assert {"category": "static", "groupTask": "Default"} in actions["NO_TASK"][
        "availableFor"
    ]
    assert actions["FARP_SPAWN"]["capability"] == {"messages": ["has no cargo"]}
    assert actions["ROE"]["option"] == "ROE" and actions["ROE"]["optionName"] == 0
    roe = options["ROE"]
    assert roe["valueSets"] == [
        {
            "categories": ["plane", "vehicle"],
            "values": [
                {"value": 0, "name": "WEAPON FREE"},
                {"value": 4, "name": "WEAPON HOLD"},
            ],
            "default": 4,
        },
        {
            "categories": ["ship"],
            "values": [{"value": 0, "name": "WEAPON FREE"}],
            "default": 0,
        },
    ]
    assert roe["missionValues"] == [{"value": 4, "count": 1}]
    assert options["AWARNESS_LEVEL"]["valueSets"] == [
        {"default": 1, "min": 0, "max": 10, "units": "timeUnits"}
    ]
    assert options["FORMATION"]["valueSets"][0]["values"] == [
        {"value": 3, "name": "Wedge"},
        {"value": 1, "name": "Line"},
    ]
    assert any("undefined AWARNESS_LEVEL" in p for p in problems)
    assert any("FORMATION plane: no default" in p for p in problems)
    assert any("'orbit'" in p for p in problems)  # a mission key no action has
    schema = entity_schema()
    for rec in actions.values():
        jsonschema.validate(rec, {**schema, "$ref": "#/definitions/Entity.Action"})
    for rec in options.values():
        jsonschema.validate(
            rec, {**schema, "$ref": "#/definitions/Entity.ActionOption"}
        )


# ---------------------------------------------------------------------------
# Generated types
# ---------------------------------------------------------------------------


# The formations series of the fixture's two formations (WorldID 3 and 1).
FORMATION_RECORDS = {
    "WEDGE": {
        "id": "WEDGE",
        "worldId": 3,
        "variants": [{"name": "Close (39 m x 36 m)"}, {"name": "Open"}],
        "defaultVariantIndex": 2,
    },
    "LINE": {"id": "LINE", "worldId": 1, "zInverse": True, "variants": [{}]},
}


def _data_dir(
    tmp_path: Path,
    actions: dict[str, dict[str, Any]],
    options: dict[str, dict[str, Any]],
) -> Path:
    d = tmp_path / "data"
    write(d / "manifest.json", json.dumps({"dcsVersion": "9.9.9.1"}))
    for name, recs in (
        ("actions", actions),
        ("options", options),
        ("formations", FORMATION_RECORDS),
    ):
        for rid, rec in recs.items():
            write(d / name / f"{rid}.json", json.dumps(rec))
    return d


def _point_overlay(ids: list[str]) -> overlays.Overlays:
    return overlays.Overlays(
        [
            {
                "series": "actions",
                "id": i,
                "field": "params[name=point]",
                "add": {"seenIn": [], "types": ["table"]},
            }
            for i in ids
        ],
        {},
    )


def test_overlay_adds_a_param_once(db: dict[str, Any]) -> None:
    actions, _, _ = _records(db)
    overlays.apply(_point_overlay(["ORBIT"]), {"actions": actions})
    names = [p["name"] for p in actions["ORBIT"]["params"]]
    assert names == sorted(names) and "point" in names
    assert actions["ORBIT"]["_source"] == {"params[name=point]": "hand-authored"}
    with pytest.raises(SystemExit):  # extracted now: stale
        overlays.apply(_point_overlay(["ORBIT"]), {"actions": actions})


def test_generated_types(db: dict[str, Any], tmp_path: Path) -> None:
    actions, options, _ = _records(db, scripts=SCRIPTS)
    overlays.apply(_point_overlay(["ORBIT"]), {"actions": actions})
    d = _data_dir(tmp_path, actions, options)
    hand = {
        "task": {
            "Orbit": {
                "description": "Hand text.",
                "params": {
                    "altitude": "Metres.",
                    "speed": {"type": "number", "description": "M/s."},
                    "point": {"type": "Vec2", "description": "Centre."},
                },
            }
        },
        "command": {"StopRoute": {"params": {"value": "Halt."}}},
    }
    files = action_types.generate(actions, options, "9.9.9.1", hand, FORMATION_RECORDS)
    assert action_types.generate_from(d, hand) == files
    assert sorted(files) == [
        "Commands.generated.yaml",
        "EnrouteTasks.generated.yaml",
        "Options.generated.yaml",
        "Tasks.generated.yaml",
    ]
    import yaml

    tasks = yaml.safe_load(files["Tasks.generated.yaml"])["types"]
    assert tasks["DcsTask.TaskId"]["values"] == {
        "FarpSpawn": "FarpSpawn",
        "NoTask": "NoTask",
        "Orbit": "Orbit",
    }
    assert tasks["DcsTask.Task.Orbit"]["description"].startswith("Hand text.")
    assert tasks["DcsTask.Task.Orbit"]["fields"]["id"]["type"] == '"Orbit"'
    fields = tasks["DcsTask.Task.OrbitParams"]["fields"]
    assert fields["altitude"]["type"] == "number"
    assert fields["altitude"]["description"].startswith(
        "Metres. Seen in: default, panel, scripts."
    )
    assert fields["speed"]["type"] == "number"
    assert fields["speed"]["description"].startswith("M/s. ")
    assert fields["point"]["type"] == "Vec2"
    assert fields["point"]["description"].startswith("Centre. Hand-authored")
    assert (
        "Also sent by DCS's scripts: attack"
        in (tasks["DcsTask.Task.Orbit"]["description"])
    )
    commands = yaml.safe_load(files["Commands.generated.yaml"])["types"]
    assert "DcsTask.Command.StopRoute" in commands["DcsTask.AnyCommand"]["anyOf"]
    assert commands["DcsTask.CommandId"]["values"]["StopRoute"] == "StopRoute"
    assert (
        commands["DcsTask.Command.StopRoute"]["fields"]["id"]["type"] == '"StopRoute"'
    )
    assert commands["DcsTask.Command.StopRoute"]["description"] == (
        "Sent by DCS's scripts: trigger.action.groupStopMoving "
        "(Scripts/ScriptingSystem.lua, setCommand)."
    )
    assert commands["DcsTask.Command.StopRouteParams"]["fields"] == {
        "value": {"type": "boolean", "description": "Halt. Seen in: scripts."}
    }
    enroute = yaml.safe_load(files["EnrouteTasks.generated.yaml"])["types"]
    assert enroute["DcsTask.EnrouteTask.EngageTargetsKey"]["values"] == {"CAP": "CAP"}
    opts = yaml.safe_load(files["Options.generated.yaml"])["types"]
    assert opts["DcsTask.OptionName"]["values"]["ROE"] == 0
    assert opts["DcsTask.Option"]["fields"]["id"]["type"] == '"Option"'
    assert opts["DcsTask.WrappedAction"]["fields"]["id"]["type"] == '"WrappedAction"'
    assert opts["DcsTask.OptionValue.ROE_plane_vehicle"]["values"] == {
        "WEAPON_FREE": 0,
        "WEAPON_HOLD": 4,
    }
    assert opts["DcsTask.OptionValue.FORMATION"]["values"] == {
        "WEDGE_CLOSE": 3 << 16 | 1,
        "WEDGE_OPEN": 3 << 16 | 2,
        "LINE": 1 << 16,
    }
    out = tmp_path / "ai"
    action_types.write(files, out)
    assert generated_drift(out, files, action_types.SUFFIX) == []
    (out / "Stale.generated.yaml").write_text("x")
    assert generated_drift(out, files, action_types.SUFFIX) == ["Stale.generated.yaml"]


@pytest.mark.parametrize(
    "hand",
    [
        {"task": {"NoSuchId": {"description": "x"}}},
        {"task": {"Orbit": {"params": {"nope": "x"}}}},
        {"bogusKind": {}},
        {"command": {"StopRoute": {"description": "x"}}},
    ],
)
def test_stale_description_overlay_fails(
    db: dict[str, Any], tmp_path: Path, hand: dict[str, Any]
) -> None:
    actions, options, _ = _records(db)
    with pytest.raises(SystemExit):
        action_types.generate(actions, options, "9.9.9.1", hand)


def test_point_forms_are_marked_alternatives() -> None:
    fields = {n: {"description": n} for n in ("point", "x", "y", "z")}
    action_types._point_forms(fields)
    assert all(
        action_types.POINT_FORMS in fields[n]["description"]
        for n in ("point", "x", "y")
    )
    assert fields["z"]["description"] == "z"
    only = {"point": {"description": "p"}}
    action_types._point_forms(only)
    assert only["point"]["description"] == "p"


def _legacy(**members: Any) -> dict[str, Any]:
    """A table in the ``api_dump.legacy`` shape: nested dicts become tables."""
    out = []
    for k, v in members.items():
        if isinstance(v, dict):
            out.append({"name": k, "type": "table", "sub": _legacy(**v)})
        else:
            out.append({"name": k, "type": "number", "value": v})
    return {"kind": "table", "members": out}


def test_option_values_add_runtime_values_and_param_types(
    db: dict[str, Any],
) -> None:
    actions, options, _ = _records(db)
    roe = {"WEAPON_FREE": 0, "OPEN_FIRE": 2, "WEAPON_HOLD": 4}
    runtime = {"AI": _legacy(Option={"Air": {"val": {"ROE": roe}}})}
    hand = {"param": {"altitude": "Distance"}}
    files = action_types.generate(
        actions, options, "9.9.9.1", hand, FORMATION_RECORDS, runtime
    )
    import yaml

    opts = yaml.safe_load(files["Options.generated.yaml"])["types"]
    roe_type = opts["DcsTask.OptionValue.ROE_plane_vehicle"]
    assert roe_type["values"] == {"WEAPON_FREE": 0, "WEAPON_HOLD": 4, "OPEN_FIRE": 2}
    assert "(OPEN_FIRE)" in roe_type["description"]
    tasks = yaml.safe_load(files["Tasks.generated.yaml"])["types"]
    assert tasks["DcsTask.Task.OrbitParams"]["fields"]["altitude"]["type"] == "Distance"
    with pytest.raises(SystemExit):  # a param name no action has
        action_types.generate(
            actions,
            options,
            "9.9.9.1",
            {"param": {"nope": "number"}},
            FORMATION_RECORDS,
        )
    with pytest.raises(SystemExit):  # a FORMATION value without a formation
        action_types.generate(actions, options, "9.9.9.1", {}, {})
