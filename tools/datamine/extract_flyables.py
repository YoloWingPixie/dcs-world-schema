"""Which aircraft types are player-flyable, from the DCS install's own declarations.

A flyable plugin (``Mods/<kind>/<plugin>/entry.lua``) declares each airframe it
makes flyable with ``make_flyable(type_id, cockpit, fm, comm)`` or the MAC
variant ``MAC_flyable(...)``. DCS skips payware flyable plugins it is not
authorized for (always so in ``--server`` mode), so the dump's
``_file_flyable`` marker misses them; the declarations in the install do not.

Each ``entry.lua`` that mentions either call runs in the Lua sandbox with the
two calls recording their first argument and every other global a permissive
stub (callable, indexable, concatenable), so ids held in locals
(``local flyable_ID = "AH-64D_BLK_II"``) resolve. A plugin that fails to run, or
declares a non-string id, fails the extraction rather than silently dropping
airframes.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any

from .common import fail, read_text
from .lua_reader import lua_execute, sandbox_exec

# Plugin roots (relative to the install) that may hold flyable entry.lua files.
PLUGIN_GLOBS = ("Mods/*/*/entry.lua", "CoreMods/*/*/entry.lua")
_DECLARES = re.compile(r"\b(?:make_flyable|MAC_flyable)\s*\(")

# env(mod_path) -> (env, ids): a sandbox env for one entry.lua and the array the
# declaring calls append to.
_ENV = r"""
local setmetatable, rawset, type, error = setmetatable, rawset, type, error
local stub_mt = {}
local function stub() return setmetatable({}, stub_mt) end
local function new_stub() return stub() end
stub_mt.__index = function(t, k) local v = stub(); rawset(t, k, v); return v end
stub_mt.__call = new_stub
for _, m in ipairs({"__concat", "__add", "__sub", "__mul", "__div", "__mod",
                    "__pow", "__unm"}) do
    stub_mt[m] = new_stub
end
stub_mt.__lt = function() return false end
stub_mt.__le = function() return false end
return function(mod_path)
    local ids = {}
    local function declare(name)
        if type(name) ~= "string" then
            error("flyable id is not a string (" .. type(name) .. ")")
        end
        ids[#ids + 1] = name
    end
    local env = {
        make_flyable = declare, MAC_flyable = declare,
        current_mod_path = mod_path, __DCS_VERSION__ = "0.0.0.0",
        string = string, table = table, math = math,
        pairs = pairs, ipairs = ipairs, next = next, select = select,
        type = type, tostring = tostring, tonumber = tonumber,
        unpack = unpack or table.unpack,
        setmetatable = setmetatable, getmetatable = getmetatable,
        rawget = rawget, rawset = rawset, rawequal = rawequal,
        pcall = pcall, error = error, assert = assert,
        print = function() end,
    }
    env._G = env
    setmetatable(env, {__index = function(t, k)
        local v = stub(); rawset(t, k, v); return v
    end})
    return env, ids
end
"""


@functools.cache
def _env_factory() -> Any:
    return lua_execute(_ENV)


def declared_in(text: str, name: str, mod_path: str) -> list[str]:
    """Flyable type ids one ``entry.lua`` text declares, in call order. Raises
    ``ValueError`` when the chunk fails to run."""
    env, ids = _env_factory()(mod_path)
    ok, err = sandbox_exec(text, name, env)
    if not ok:
        raise ValueError(str(err))
    return [ids[i] for i in range(1, len(ids) + 1)]


def declared_flyables(install_dir: Path) -> dict[str, str]:
    """Flyable type id -> declaring plugin dir (install-relative, ``/``-separated)."""
    declared: dict[str, str] = {}
    failures: list[str] = []
    entries = sorted(p for g in PLUGIN_GLOBS for p in install_dir.glob(g))
    for entry in entries:
        text = read_text(entry)
        if not _DECLARES.search(text):
            continue
        plugin = entry.parent.relative_to(install_dir).as_posix()
        try:
            ids = declared_in(text, str(entry), str(entry.parent))
        except ValueError as e:
            failures.append(f"{plugin}: {e}")
            continue
        if not ids:
            failures.append(f"{plugin}: mentions make_flyable but declared nothing")
        for uid in ids:
            declared.setdefault(uid, plugin)
    if failures:
        fail("flyable declarations unreadable:\n  " + "\n  ".join(failures))
    if not declared:
        fail(f"no make_flyable/MAC_flyable declarations under {install_dir}")
    return dict(sorted(declared.items()))


def missing_units(declared: dict[str, str], units_by_type: dict[str, Any]) -> list[str]:
    """Declared flyable ids with no ``db.Units`` record, as ``id (plugin)``."""
    return [f"{u} ({p})" for u, p in declared.items() if u not in units_by_type]


def check_coverage(declared: dict[str, str], units_by_type: dict[str, Any]) -> None:
    """Fail when a declared flyable has no unit record: its definition is
    somewhere the dump does not reach (e.g. an authorized-only plugin)."""
    if missing := missing_units(declared, units_by_type):
        fail(
            f"{len(missing)} declared flyable(s) missing from db.Units: "
            + ", ".join(missing)
        )


def flyable_types(
    units_by_type: dict[str, dict[str, Any]], declared: dict[str, str]
) -> set[str]:
    """Types the dump marks flyable (``_file_flyable``) or the install declares."""
    return {
        t
        for t, rec in units_by_type.items()
        if rec.get("_file_flyable") is not None or t in declared
    }
