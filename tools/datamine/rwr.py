"""DCS's own RWR tables, joined exactly to unit types and projectiles.

* ``AN_ALR_SymbolsBase.lua``: ``symbols`` (``{wsType tuple, symbol}``) and
  ``symbols_strings`` (``[unit type or projectile name] = symbol``).
* ``AN_ALR_HarmIDs.lua``: ``symbolID`` (``{code, wsType tuple}``) and
  ``symbols_stringsID`` (``{code, name, ...}``), the HARM/ALIC codes.

Both come from the DCS install and run in the Lua sandbox with their
``dofile``'d ``wsTypes_*.lua`` / ``Scripts/Database/wsTypes.lua`` (read from the
install only). Each wsType key keeps the name of the global it was written as.
A tuple key joins the units whose ``attribute`` and the projectiles whose
``ws_type`` carry exactly that numeric 4-tuple, through the dump hook's
``_G/__wstype_ids__.lua``; a string key joins the unit type or projectile of
that name. Keys that join nothing, keys DCS wrote as a bare level-4 number or
an undefined global (DCS matches nothing by them) are reported. A unit or
projectile may carry several HARM/ALIC codes (``alic``, sorted numerically,
e.g. USS_Arleigh_Burke_IIa gets 412 by name and TICONDEROGA_'s 315 by the
wsType it shares); two different RWR symbols fail. Units' codes go on their threats (``extract_threats``); projectiles'
(active-radar missiles) on their ``Entity.Weapon`` records.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lupa import lua_type

from .common import fail, read_text
from .lua_reader import LuaReader, as_dict, lua_execute, sandbox_exec

WSTYPE_IDS = "__wstype_ids__.lua"
COCKPIT = Path("Scripts/Aircrafts/_Common/Cockpit")
SYMBOLS = COCKPIT / "AN_ALR_SymbolsBase.lua"
HARM_IDS = COCKPIT / "AN_ALR_HarmIDs.lua"

Tuple = tuple[int, int, int, int]


@dataclass(frozen=True)
class WsTypeIds:
    """``_G/__wstype_ids__.lua``: name -> the record's distinct raw tuples."""

    units: dict[str, list[Tuple]]
    stores: dict[str, list[Tuple]]
    projectiles: dict[str, list[Tuple]]
    ammunition: dict[str, list[Tuple]]

    def by_tuple(self, family: str) -> dict[Tuple, list[str]]:
        out: dict[Tuple, list[str]] = {}
        for name, tuples in sorted(getattr(self, family).items()):
            for t in tuples:
                out.setdefault(t, []).append(name)
        return out


def _tuples(value: Any) -> list[Tuple]:
    out = []
    for t in value if isinstance(value, list) else []:
        if (
            isinstance(t, list)
            and len(t) == 4
            and all(isinstance(n, int) and not isinstance(n, bool) for n in t)
        ):
            out.append((t[0], t[1], t[2], t[3]))
        else:
            fail(f"{WSTYPE_IDS}: not a numeric 4-tuple: {t!r}")
    return out


def load_wstype_ids(reader: LuaReader, g_dir: Path) -> WsTypeIds:
    """The hook's raw wsType ids; a dump without them fails."""
    path = g_dir / WSTYPE_IDS
    if not path.is_file():
        fail(
            f"no {WSTYPE_IDS} in {g_dir}: dump predates wsType id capture; "
            "re-dump with the current hook (task datamine)"
        )
    dumped = reader.read_file(path)
    if dumped is None:
        fail(f"{path} failed to parse: {reader.stats.failures[-1][1]}")
    families = {
        f: {k: _tuples(v) for k, v in as_dict(as_dict(dumped).get(f)).items()}
        for f in ("units", "stores", "projectiles", "ammunition")
    }
    return WsTypeIds(**families)


# env, defs = make(read): globals written by the chunk land in `defs`. A global
# read by the top-level chunk (not by a dofile'd file) is returned as
# {__ident = name, __value = value}, so each table entry keeps the name its key
# was written as. dofile(path) runs install text with the same env.
_ENV = """
local load, error, setmetatable, tostring = load, error, setmetatable, tostring
return function(read)
  local defs, depth = {}, 0
  local env = setmetatable({}, {
    __index = function(_, k)
      local v = defs[k]
      if depth == 0 and k ~= 'dofile' then return { __ident = k, __value = v } end
      return v
    end,
    __newindex = function(_, k, v) defs[k] = v end,
  })
  defs.dofile = function(path)
    local text = read(path)
    if text == nil then error('dofile: no install file ' .. tostring(path)) end
    local fn, err = load(text, '=' .. path, 't', env)
    if not fn then error(err) end
    depth = depth + 1
    fn()
    depth = depth - 1
  end
  return env, defs
end
"""


def _install_reader(install_dir: Path) -> Callable[[str], str | None]:
    root = install_dir.resolve()

    def read(rel: str) -> str | None:
        path = (root / str(rel)).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        return read_text(path)

    return read


def run_install_script(install_dir: Path, rel: Path) -> Any:
    """``defs`` (a Lua table) of the install file ``rel``, run in the sandbox."""
    try:
        text = read_text(install_dir / rel)
    except FileNotFoundError:
        fail(f"no {rel.as_posix()} in {install_dir} (needed for the threats series)")
    env, defs = lua_execute(_ENV)(_install_reader(install_dir))
    ok, err = sandbox_exec(text, rel.as_posix(), env)
    if not ok:
        fail(f"{rel.as_posix()}: {err}")
    return defs


@dataclass(frozen=True)
class Key:
    """A table key: a wsType global (``ident``; ``tuple`` when it holds a
    numeric 4-tuple, ``number`` when a bare number) or a ``name`` string."""

    ident: str | None = None
    tuple: Tuple | None = None
    number: float | None = None
    name: str | None = None

    def __str__(self) -> str:
        if self.name is not None:
            return repr(self.name)
        if self.tuple is not None:
            return f"{self.ident} {{{', '.join(map(str, self.tuple))}}}"
        if self.number is not None:
            return f"{self.ident} (the number {self.number:g}, not a wsType tuple)"
        return f"{self.ident} (undefined)"


@dataclass(frozen=True)
class Entry:
    table: str  # symbols, symbols_strings, symbolID, symbols_stringsID
    key: Key
    value: str  # RWR symbol or HARM/ALIC code


def _key(value: Any, where: str) -> Key:
    if isinstance(value, str):
        return Key(name=value)
    if lua_type(value) != "table" or not isinstance(value["__ident"], str):
        fail(f"{where}: key {value!r} is neither a string nor a global")
    ident, inner = value["__ident"], value["__value"]
    if inner is None:
        return Key(ident=ident)
    if isinstance(inner, (int, float)) and not isinstance(inner, bool):
        return Key(ident=ident, number=inner)
    if lua_type(inner) == "table":
        slots = [inner[i] for i in range(1, 5)]
        if len(inner) == 4 and all(
            isinstance(n, (int, float)) and n == int(n) for n in slots
        ):
            a, b, c, d = (int(n) for n in slots)
            return Key(ident=ident, tuple=(a, b, c, d))
    fail(f"{where}: {ident} is not a wsType 4-tuple")


def _value(value: Any, where: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:g}"
    fail(f"{where}: value {value!r} is not a string or number")


def _array(defs: Any, name: str, rel: Path) -> list[Any]:
    table = defs[name]
    if lua_type(table) != "table":
        fail(f"{rel.as_posix()}: no `{name}` table")
    return [table[i] for i in range(1, len(table) + 1)]


def read_tables(install_dir: Path) -> tuple[list[Entry], dict[str, int]]:
    """(every entry of the four tables, in file order; the numeric ``wsType_*``
    globals the install's wsTypes.lua defines)."""
    entries: list[Entry] = []
    symbols = run_install_script(install_dir, SYMBOLS)
    for i, e in enumerate(_array(symbols, "symbols", SYMBOLS), 1):
        where = f"{SYMBOLS.name} symbols[{i}]"
        entries.append(Entry("symbols", _key(e[1], where), _value(e[2], where)))
    strings = symbols["symbols_strings"]
    if lua_type(strings) != "table":
        fail(f"{SYMBOLS.as_posix()}: no `symbols_strings` table")
    for name, value in sorted(strings.items(), key=lambda kv: str(kv[0])):
        where = f"{SYMBOLS.name} symbols_strings[{name!r}]"
        entries.append(
            Entry("symbols_strings", _key(name, where), _value(value, where))
        )

    harm = run_install_script(install_dir, HARM_IDS)
    for i, e in enumerate(_array(harm, "symbolID", HARM_IDS), 1):
        where = f"{HARM_IDS.name} symbolID[{i}]"
        entries.append(Entry("symbolID", _key(e[2], where), _value(e[1], where)))
    for i, e in enumerate(_array(harm, "symbols_stringsID", HARM_IDS), 1):
        where = f"{HARM_IDS.name} symbols_stringsID[{i}]"
        code = _value(e[1], where)
        for j in range(2, len(e) + 1):
            entries.append(Entry("symbols_stringsID", _key(e[j], where), code))

    ws_types = {
        str(k): int(v)
        for k, v in symbols.items()
        if isinstance(k, str)
        and k.startswith("wsType_")
        and isinstance(v, (int, float))
        and v == int(v)
    }
    return entries, ws_types


# The tables whose value is the RWR symbol; the others hold HARM/ALIC codes.
SYMBOL_TABLES = ("symbols", "symbols_strings")


@dataclass
class RwrJoin:
    """Per unit type / projectile name: ``{"rwrSymbol": str, "alic": [str]}``."""

    units: dict[str, dict[str, Any]] = field(default_factory=dict)
    projectiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)  # keys joining nothing
    unkeyed: list[str] = field(default_factory=list)  # bare numbers / undefined
    joined: dict[str, int] = field(default_factory=dict)  # table -> entries joined


def join(
    entries: list[Entry],
    unit_types: set[str],
    projectile_names: set[str],
    ids: WsTypeIds,
) -> RwrJoin:
    """Join each entry to the unit types / projectiles its key names exactly."""
    out = RwrJoin()
    units_by = ids.by_tuple("units")
    projs_by = ids.by_tuple("projectiles")
    conflicts: list[str] = []
    for e in entries:
        k = e.key
        label = f"{e.table} {k}"
        if k.name is not None:
            units = [k.name] if k.name in unit_types else []
            projs = [k.name] if k.name in projectile_names else []
        elif k.tuple is not None:
            units = [u for u in units_by.get(k.tuple, []) if u in unit_types]
            projs = [p for p in projs_by.get(k.tuple, []) if p in projectile_names]
        else:
            out.unkeyed.append(label)
            continue
        if not units and not projs:
            out.unmatched.append(label)
            continue
        out.joined[e.table] = out.joined.get(e.table, 0) + 1
        for target, names in ((out.units, units), (out.projectiles, projs)):
            for name in names:
                slot = target.setdefault(name, {})
                if e.table not in SYMBOL_TABLES:
                    codes = slot.setdefault("alic", [])
                    if e.value not in codes:
                        codes.append(e.value)
                        codes.sort(key=_code_order)
                    continue
                prev = slot.setdefault("rwrSymbol", e.value)
                if prev != e.value:
                    conflicts.append(
                        f"{name}: rwrSymbol {prev!r} and {e.value!r} ({label})"
                    )
    if conflicts:
        fail("RWR tables give one emitter different symbols: " + "; ".join(conflicts))
    return out


def _code_order(code: str) -> tuple[int, float, str]:
    try:
        return (0, float(code), code)
    except ValueError:
        return (1, 0.0, code)


def apply_to_weapons(joined: RwrJoin, weapons: dict[str, dict[str, Any]]) -> None:
    """Put each joined projectile's ``rwrSymbol``/``alic`` on its weapon record
    (the active-radar missiles DCS shows on the RWR themselves)."""
    for name, codes in sorted(joined.projectiles.items()):
        weapons[name].update(codes)


def ammunition_report(ids: WsTypeIds) -> list[str]:
    """One line per raw unit ``type_ammunition`` tuple that no single
    projectile carries exactly, with the projectiles sharing its levels 1, 2
    and 4 (the hook's slot-4 fallback)."""
    exact = ids.by_tuple("projectiles")
    l124: dict[tuple[int, int, int], set[str]] = {}
    for t, names in exact.items():
        l124.setdefault((t[0], t[1], t[3]), set()).update(names)
    lines = []
    for unit, tuples in sorted(ids.ammunition.items()):
        for t in tuples:
            names = sorted(set(exact.get(t, [])))
            if len(names) == 1:
                continue
            alike = sorted(l124.get((t[0], t[1], t[3]), set()))
            lines.append(
                f"{unit}: type_ammunition {{{', '.join(map(str, t))}}} exactly matches "
                f"{names or 'no projectile'}; by levels 1, 2, 4: {alike or 'none'}"
            )
    return lines


def check_ws_type_constants(install: dict[str, int], dumped: dict[str, int]) -> None:
    """The install's wsType_* levels must be the dump's (the tuples compare
    install constants with dumped ids)."""
    differ = sorted(
        f"{n}: install {v}, dump {dumped[n]}"
        for n, v in install.items()
        if n in dumped and dumped[n] != v
    )
    if differ:
        fail(f"install wsTypes.lua and the dump disagree: {differ}")
