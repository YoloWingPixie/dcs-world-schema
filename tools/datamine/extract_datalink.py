"""Extract ``Entity.Datalink`` records from the mission editor's datalink
descriptors.

A flyable airframe's ``datalinks`` table maps a datalink type to a descriptor
file (``Datalinks\\Link16.lua``), resolved like MissionEditor/modules/
me_datalinks.lua ``loadDescriptors`` does: next to the airframe's ``_file`` in
the install. The descriptor is the mission editor's datalink page; it holds the
network limits only as code, so each descriptor is run in the Lua sandbox with
stand-ins for the me_datalinks.lua callbacks: a default datalink for a lone
unit (``getDefault``, ``init``), then every ``b_AddUnit*`` button it registers
is pressed with a pool of same-coalition units of another group until the
list it fills stops growing. From that:

- ``maxTeamMembers``: the size the ``network.teamMembers`` list (IDM: preset
  1's ``network.presets[1].members``) stops at, the unit itself included;
  ``supportsTeamMembers`` and ``supportsCrossFlightTeam``: it has such a list
  and accepts units of another group into it.
- ``maxDonors``: the size ``network.donors`` stops at; 0 without a donor list.
- ``canBeLink16Donor``: the airframe declares the ``AddPropAircraft`` property
  (``STN_L16``) the Link16 descriptors pool their candidate units by
  (``getUnitsGroupsWithAddPropName``).

A declared datalink type outside ``Entity.DatalinkType``, a missing
descriptor, a list that never stops growing, or a button whose list is none
of the above stops the extraction."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, cast

from .common import fail
from .lua_reader import (
    INSTRUCTION_LIMIT,
    array_entries,
    as_dict,
    as_string,
    lua_execute,
    lua_to_py,
)

# ``datalinks`` keys (Entity.DatalinkType values), in me_datalinks.lua's
# preference order for a unit declaring several.
_KNOWN_KINDS = ["IDM", "Link16", "SADL"]
LINK16 = "Link16"
# Same-coalition units of another group offered to the descriptor's buttons;
# more than any list may hold, so a list that takes them all has no limit.
POOL = 64
_TEAM_LISTS = ("teamMembers", "presets[1].members")
_DONOR_LIST = "donors"

# measure(text, name, pool, limit) -> {poolKeys = {key...}, buttons = {name =
# {list = <list name>, before = n, after = n}}} or raises. Each button is
# pressed on a fresh descriptor instance.
_HARNESS = """
local load, pcall, error, tostring, setmetatable = load, pcall, error, tostring, setmetatable
local pairs, ipairs, type, sethook = pairs, ipairs, type, debug.sethook
local lib = {table = table, string = string, math = math, tonumber = tonumber}

local function copy(dest, source, seen)
    for k, v in pairs(source) do
        if type(v) == "table" then
            if seen[v] == nil then
                dest[k] = dest[k] or {}
                seen[v] = dest[k]
                copy(dest[k], v, seen)
            else
                dest[k] = seen[v]
            end
        else
            dest[k] = v
        end
    end
end

local function lists(dl)
    local out = {}
    local network = type(dl) == "table" and dl.network or nil
    if type(network) ~= "table" then return out end
    for k, v in pairs(network) do
        if k == "presets" and type(v) == "table" and type(v[1]) == "table" then
            out["presets[1].members"] = v[1].members
        elseif type(v) == "table" then
            out[k] = v
        end
    end
    return out
end

local function instance(text, name, pool)
    local callbacks, keys = {}, {}
    local other = {}
    for i = 1, pool do other[i] = 100 + i end
    local groups = {[1] = {1}, [2] = other}
    local env = {
        print = function() end, pairs = pairs, ipairs = ipairs, type = type,
        tostring = tostring, table = lib.table, string = lib.string,
        tonumber = lib.tonumber, math = lib.math,
        traverseTable = function() end,
        recursiveCopyTable = function(dest, source) copy(dest, source, {}) end,
        onAction = function(widget, action, arg)
            if action == "add_callback" and type(arg) == "table" and arg[1] == "onChange" then
                callbacks[widget] = arg[2]
            end
        end,
        getDatalinksByUnitId = function() return nil end,
        getAddPropByUnitId = function()
            return setmetatable({}, {__index = function() return "1" end})
        end,
        getNameByUnitId = function(id) return "unit " .. tostring(id) end,
        getNameByGroupId = function(id) return "group " .. tostring(id) end,
        getUnitsGroupsWithAddPropName = function(key)
            keys[key] = true
            return groups
        end,
        getCoalitionByUnitId = function() return "blue" end,
    }
    local fn, err = load(text, name, "t", env)
    if not fn then error(err) end
    fn()
    local unit = {unitId = 1, index = 1, name = "unit 1", AddPropAircraft = {}, datalinks = {}}
    local dl = env.getDefault({unit = unit, group = {unit}})
    env.init(dl, 1, 1)
    return dl, callbacks, keys
end

local function measure(text, name, pool)
    local _, callbacks, keys = instance(text, name, pool)
    local out = {poolKeys = {}, buttons = {}}
    for key in pairs(keys) do out.poolKeys[#out.poolKeys + 1] = key end
    for button in pairs(callbacks) do
        if button:sub(1, 9) == "b_AddUnit" then
            local dl, cbs = instance(text, name, pool)
            local before = {}
            for list, t in pairs(lists(dl)) do before[list] = #t end
            for _ = 1, pool + 1 do cbs[button]({}, dl) end
            local grew = {}
            for list, t in pairs(lists(dl)) do
                if #t ~= (before[list] or 0) then
                    grew[#grew + 1] = {list = list, before = before[list] or 0, after = #t}
                end
            end
            out.buttons[button] = grew
        end
    end
    return out
end

return function(text, name, pool, limit)
    sethook(function() error("instruction limit exceeded") end, "", limit)
    local ok, res = pcall(measure, text, name, pool)
    sethook()
    if not ok then error(tostring(res)) end
    return res
end
"""


@functools.cache
def _measure() -> Any:
    return lua_execute(_HARNESS)


def descriptor_path(install_dir: Path, unit_file: str, descriptor: str) -> Path:
    """me_datalinks.lua ``getCorrectPath``: ``descriptor`` next to the unit's
    ``_file`` in the install."""
    base = (install_dir / unit_file.replace("\\", "/")).parent
    return base / descriptor.replace("\\", "/")


def measure_descriptor(text: str, where: str) -> dict[str, Any]:
    """The pool key(s) and per-button list growth of one descriptor."""
    try:
        raw = _measure()(text, where, POOL, INSTRUCTION_LIMIT)
    except Exception as exc:
        fail(f"{where}: datalink descriptor did not run: {exc}")
    return cast(dict[str, Any], lua_to_py(raw))


def capabilities(measured: dict[str, Any], where: str) -> dict[str, Any]:
    """Team and donor limits from ``measure_descriptor``'s button results."""
    buttons = as_dict(measured.get("buttons"))
    team: list[dict[str, Any]] = []
    donors: list[dict[str, Any]] = []
    for button, grew in sorted(buttons.items()):
        grew = [g for g in array_entries(grew) if isinstance(g, dict)]
        if len(grew) != 1:
            fail(f"{where}: button {button} fills {len(grew)} lists, expected 1")
        g = grew[0]
        if g["after"] - g["before"] >= POOL:
            fail(f"{where}: {g['list']} took all {POOL} offered units; no limit found")
        if g["list"] in _TEAM_LISTS:
            team.append(g)
        elif g["list"] == _DONOR_LIST:
            donors.append(g)
        else:
            fail(f"{where}: button {button} fills unknown list {g['list']!r}")
    if len(team) != 1 or len(donors) > 1:
        fail(
            f"{where}: expected one team-member and at most one donor button, "
            f"got {len(team)} and {len(donors)}"
        )
    return {
        "supportsTeamMembers": True,
        "supportsCrossFlightTeam": team[0]["after"] > team[0]["before"],
        "maxTeamMembers": team[0]["after"],
        "maxDonors": donors[0]["after"] if donors else 0,
    }


def _add_prop_ids(unit: dict[str, Any]) -> set[str]:
    return {
        i
        for p in array_entries(unit.get("AddPropAircraft"))
        if isinstance(p, dict) and (i := as_string(p.get("id")))
    }


def build_datalinks(
    units_by_type: dict[str, dict[str, Any]], flyable: set[str], install_dir: Path
) -> dict[str, dict[str, Any]]:
    """Datalink records keyed by (and with the id of) the ``flyable`` aircraft type."""
    measured: dict[Path, dict[str, Any]] = {}
    declared: dict[str, tuple[str, Path]] = {}
    for atype in sorted(units_by_type):
        if atype not in flyable:
            continue
        unit = units_by_type[atype]
        links = as_dict(unit.get("datalinks"))
        if not links:
            continue
        unknown = sorted(set(links) - set(_KNOWN_KINDS))
        if unknown:
            fail(f"{atype}: datalinks {unknown} are no Entity.DatalinkType")
        kind = next(k for k in _KNOWN_KINDS if k in links)
        unit_file = as_string(unit.get("_file"))
        descriptor = as_string(links[kind])
        if unit_file is None or descriptor is None:
            fail(f"{atype}: datalinks.{kind} needs `_file` and a descriptor path")
        path = descriptor_path(install_dir, unit_file, descriptor)
        if not path.is_file():
            fail(f"{atype}: datalinks.{kind} descriptor {path} not found")
        if path not in measured:
            measured[path] = measure_descriptor(
                path.read_text(encoding="utf-8", errors="replace"), str(path)
            )
        declared[atype] = (kind, path)

    link16_keys = {
        k
        for kind, path in declared.values()
        if kind == LINK16
        for k in array_entries(measured[path].get("poolKeys"))
    }
    if len(link16_keys) != 1:
        fail(
            f"Link16 descriptors pool units by {sorted(link16_keys)}, expected one key"
        )
    (donor_key,) = link16_keys

    datalinks: dict[str, dict[str, Any]] = {}
    for atype, (kind, path) in declared.items():
        caps = capabilities(measured[path], f"{atype} {path}")
        datalinks[atype] = {
            "id": atype,
            "datalinkType": kind,
            "canBeLink16Donor": donor_key in _add_prop_ids(units_by_type[atype]),
            **caps,
        }
    return datalinks
