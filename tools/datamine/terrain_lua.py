"""Evaluate a terrain's plain-Lua files (``entry.lua``, ``Beacons.lua``,
``Radio.lua``) and the install scripts they ``dofile`` in the shared sandbox.

The env holds the pure Lua libraries the scripts use, ``dofile`` resolved
against the install root (run in the same env, under the same instruction
limit), and ``require`` for exactly ``i_18n`` (``translate`` is the identity, so
display names are DCS's untranslated source strings) and ``utils`` (an empty
table: only ``coordinates()`` in BeaconTypes.lua uses it, which then fails
loudly). Any other ``require`` is an error.

Numeric DCS constants the files use (``BEACON_TYPE_*``, ``MODULATIONTYPE_*``,
the ``HF``/``VHF_LOW``/``VHF_HI``/``UHF`` band keys) are read from the same
install scripts: every global number a constants script defines.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .common import fail, read_text, warn
from .lua_reader import lua_execute, lua_to_py, sandbox_exec

BEACON_TYPES_SCRIPT = "Scripts/World/Radio/BeaconTypes.lua"
MODULATION_SCRIPT = "Scripts/World/Radio/ModulationTypes.lua"
BANDS_SCRIPT = "Scripts/World/Radio/FrequencyBands.lua"
BEACON_SITES_SCRIPT = "Scripts/World/Radio/BeaconSites.lua"

# env(read) -> env. ``read(path)`` returns the install file's text or nil.
# radio_channels(t): a Radio.lua ``frequency`` table ({[band] = {mod, hz}}) as
# an array of {band, modulation, hz} sorted by band (numeric keys from 0 do
# not survive the generic table conversion).
_ENV = r"""
local load, error, type, tostring, pairs, table = load, error, type, tostring, pairs, table
-- DCS runs Lua 5.1: math.pow is gone from the sandbox's Lua.
local math51 = {}
for k, v in pairs(math) do math51[k] = v end
math51.pow = function(a, b) return a ^ b end
local function new_env(read)
    local env = {
        string = string, table = table, math = math51,
        pairs = pairs, ipairs = ipairs, next = next, select = select,
        type = type, tostring = tostring, tonumber = tonumber,
        unpack = unpack or table.unpack,
        setmetatable = setmetatable, getmetatable = getmetatable,
        rawget = rawget, rawset = rawset, pcall = pcall, error = error,
        assert = assert, print = function() end,
        package = {path = ""}, USE_TERRAIN4 = true,
    }
    env._G = env
    local i18n = {translate = function(s) return s end}
    env._ = i18n.translate
    env.require = function(name)
        if name == "i_18n" then return i18n end
        if name == "utils" then return {} end
        error("require of unsupported module " .. tostring(name))
    end
    env.dofile = function(path)
        local text = read(path)
        if text == nil then error("dofile: no such install file " .. tostring(path)) end
        local fn, err = load(text, path, "t", env)
        if not fn then error(err) end
        return fn()
    end
    env.declare_plugin = function(id, t) env.__plugin = t end
    env.plugin_done = function() end
    return env
end
local function radio_channels(t)
    local out = {}
    for band, v in pairs(t or {}) do
        if type(v) ~= "table" then error("radio frequency entry is not a table") end
        out[#out + 1] = {band = band, modulation = v[1], hz = v[2]}
    end
    table.sort(out, function(a, b) return a.band < b.band end)
    return out
end
return new_env, radio_channels
"""


@functools.cache
def _helpers() -> tuple[Any, Any]:
    return cast(tuple[Any, Any], lua_execute(_ENV))


@dataclass
class TerrainFiles:
    directory: str  # terrain dir name under Mods/terrains
    plugin: dict[str, Any]  # entry.lua's declare_plugin table
    beacons: list[dict[str, Any]]
    radio: list[dict[str, Any]]


def _find(directory: Path, name: str) -> Path | None:
    """``directory/name`` matched case-insensitively (DCS varies the case)."""
    hits = [p for p in directory.iterdir() if p.name.lower() == name.lower()]
    if len(hits) > 1:
        fail(f"{directory}: several files named {name} (case-insensitive)")
    return hits[0] if hits else None


class TerrainLua:
    def __init__(self, install_dir: Path) -> None:
        self.install_dir = install_dir

    def _read(self, rel: Any) -> str | None:
        path = self.install_dir / str(rel)
        try:
            return read_text(path)
        except (FileNotFoundError, IsADirectoryError):
            return None

    @staticmethod
    def _check_utf8(path: Path) -> None:
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as e:
            warn(f"{path} is not UTF-8 ({e}); bad bytes read as U+FFFD")

    def run(self, path: Path) -> Any:
        """The env after running ``path`` (install-relative dofiles resolve;
        ``current_mod_path`` is the file's directory, as for a plugin)."""
        new_env, _ = _helpers()
        env = new_env(self._read)
        env["current_mod_path"] = str(path.parent)
        ok, err = sandbox_exec(read_text(path), str(path), env)
        if not ok:
            fail(f"{path}: {err}")
        return env

    def constants(self, rel: str) -> dict[str, int]:
        """Every global number an install constants script defines."""
        env = self.run(self.install_dir / rel)
        out = {
            str(k): int(v)
            for k, v in env.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        if not out:
            fail(f"{rel} defines no numeric constants")
        return out

    def plugin(self, directory: Path) -> dict[str, Any]:
        """The terrain's ``entry.lua`` ``declare_plugin`` table."""
        entry = _find(directory, "entry.lua")
        if entry is None:
            fail(f"{directory}: no entry.lua")
        plugin = lua_to_py(self.run(entry)["__plugin"])
        if not isinstance(plugin, dict):
            fail(f"{entry}: declare_plugin was not called with a table")
        return plugin

    def terrain(self, directory: Path) -> TerrainFiles:
        plugin = self.plugin(directory)
        beacons: list[dict[str, Any]] = []
        radio: list[dict[str, Any]] = []
        if (path := _find(directory, "beacons.lua")) is not None:
            self._check_utf8(path)
            beacons = self._array(self.run(path)["beacons"], path, "beacons")
        if (path := _find(directory, "radio.lua")) is not None:
            self._check_utf8(path)
            env = self.run(path)
            _, radio_channels = _helpers()
            table = env["radio"]
            raw = self._array(table, path, "radio")
            for i, rec in enumerate(raw, start=1):
                rec["frequency"] = self._array(
                    radio_channels(table[i]["frequency"]), path, "frequency"
                )
            radio = raw
        return TerrainFiles(directory.name, plugin, beacons, radio)

    def _array(self, value: Any, path: Path, name: str) -> list[Any]:
        if value is None:
            fail(f"{path}: defines no `{name}` table")
        py = lua_to_py(value)
        if py == {}:
            return []
        if not isinstance(py, list):
            fail(f"{path}: `{name}` is not an array")
        return py
