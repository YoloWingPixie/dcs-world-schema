"""The empty mission the per-terrain runtime pass loads (one per terrain).

A ``.miz`` is a zip holding what the mission editor's ``me_mission.save``
writes: ``mission``, ``warehouses``, ``theatre`` and
``l10n/DEFAULT/{dictionary,mapResource}`` (``options`` is optional: the
editor's ``load`` reads it only when present, and it is omitted). The
``mission`` table has the keys ``me_mission.create_new_mission`` sets, with no
groups or units:

* ``version``: the install's ``VERSION_MISSION`` (``me_mission.lua``).
* ``date``: 1 January of the install's build year (``autoupdate.cfg``
  ``timestamp``), ``start_time`` 28800 (the editor's default when a terrain
  gives none). The hook reads this date for ``magvar.init``, so the magnetic
  variation's reference date is fixed per DCS build.
* ``weather``: ``vdata`` of ``MissionEditor/data/scripts/weather/default.lua``.
* ``coalitions``: ``blue``/``red`` of
  ``MissionEditor/data/scripts/default_coalitions.lua``, ``neutrals`` empty;
  each ``coalition`` has no countries and a bullseye at the map origin (the
  API probe's mission, ``probe_mission``, fills this table in).
* ``groundControl`` as ``me_roles.initData`` builds it, with no roles.
* Empty ``trig``, ``triggers.zones``, ``result``, ``goals``, ``failures``,
  ``forcedOptions``, ``trigrules``, ``requiredModules``, picture lists; the
  description strings are empty dictionary entries.

Output is deterministic: sorted Lua keys, fixed zip entry order and times.
"""

from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path
from typing import Any

from tools.package.lua_data import is_lua_name, lua_string

from .common import autoupdate_cfg, fail, read_text
from .lua_reader import lua_to_py, sandbox_exec

ME_MISSION = "MissionEditor/modules/me_mission.lua"
DEFAULT_WEATHER = "MissionEditor/data/scripts/weather/default.lua"
DEFAULT_COALITIONS = "MissionEditor/data/scripts/default_coalitions.lua"
START_TIME = 28800  # me_mission.create_new_mission default (08:00)
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
DICT_KEYS = (
    "descriptionText",
    "descriptionRedTask",
    "descriptionBlueTask",
    "descriptionNeutralsTask",
    "sortie",
)

_VERSION_MISSION = re.compile(r"^\s*local\s+VERSION_MISSION\s*=\s*(\d+)", re.M)
_TIMESTAMP = re.compile(r"^(\d{4})\d{4}-\d{6}$")


def lua_literal(value: Any, indent: str = "") -> str:
    """``value`` (dict/list/str/number/bool) as a Lua literal, keys sorted."""
    inner = indent + "    "
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite number {value}")
        return repr(value)
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, list):
        if not value:
            return "{}"
        rows = [
            f"{inner}[{i}] = {lua_literal(v, inner)}," for i, v in enumerate(value, 1)
        ]
        return "\n" + indent + "{\n" + "\n".join(rows) + f"\n{indent}}}"
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = []
        for k in sorted(value, key=lambda k: (not isinstance(k, int), str(k))):
            key = f"[{k}]" if isinstance(k, int) else f"[{lua_string(k)}]"
            rows.append(f"{inner}{key} = {lua_literal(value[k], inner)},")
        return "\n" + indent + "{\n" + "\n".join(rows) + f"\n{indent}}}"
    raise TypeError(f"no Lua literal for {type(value).__name__}")


def _assignment(name: str, value: Any) -> str:
    return f"{name} = {lua_literal(value)}\n"


def build_year(install_dir: Path) -> int:
    """The year of the install's ``autoupdate.cfg`` ``timestamp`` (``YYYYMMDD-hhmmss``)."""
    stamp = autoupdate_cfg(install_dir).get("timestamp")
    m = _TIMESTAMP.match(stamp) if isinstance(stamp, str) else None
    if not m:
        fail(
            f"{install_dir / 'autoupdate.cfg'}: no build timestamp (YYYYMMDD-hhmmss); got {stamp!r}"
        )
    return int(m.group(1))


def _install_global(install_dir: Path, rel: str, name: str) -> Any:
    path = install_dir / rel
    try:
        text = read_text(path)
    except FileNotFoundError:
        fail(f"{path}: missing (the empty mission's defaults come from it)")
    ok, env = sandbox_exec(text, str(path))
    if not ok:
        fail(f"{path}: {env}")
    value = lua_to_py(env[name])
    if not isinstance(value, dict):
        fail(f"{path}: `{name}` is not a table")
    return value


def install_defaults(install_dir: Path) -> dict[str, Any]:
    """The install values the mission is built from."""
    path = install_dir / ME_MISSION
    try:
        m = _VERSION_MISSION.search(read_text(path))
    except FileNotFoundError:
        m = None
    if not m:
        fail(f"{path}: no `local VERSION_MISSION = N`")
    coalitions = _install_global(install_dir, DEFAULT_COALITIONS, "coalitions")
    for side in ("blue", "red"):
        ids = coalitions.get(side)
        if ids == {}:
            ids = []
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            fail(f"{install_dir / DEFAULT_COALITIONS}: `{side}` is not a list of ids")
        coalitions[side] = ids
    return {
        "version": int(m.group(1)),
        "weather": _install_global(install_dir, DEFAULT_WEATHER, "vdata"),
        "coalitions": {
            "blue": coalitions["blue"],
            "red": coalitions["red"],
            "neutrals": [],
        },
        "year": build_year(install_dir),
    }


def empty_mission(
    theatre: str, defaults: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """(``mission`` table, ``dictionary``) of the empty mission on ``theatre``."""
    if not is_lua_name(theatre):
        fail(f"theatre id {theatre!r} is not a plain identifier")
    empty_result: dict[str, list[Any]] = {"actions": [], "conditions": [], "func": []}
    mission: dict[str, Any] = {
        "version": defaults["version"],
        "theatre": theatre,
        "date": {"Year": defaults["year"], "Month": 1, "Day": 1},
        "start_time": START_TIME,
        "weather": defaults["weather"],
        "coalitions": defaults["coalitions"],
        "coalition": {
            side: {
                "name": side,
                "bullseye": {"x": 0, "y": 0},
                "nav_points": [],
                "country": [],
            }
            for side in ("blue", "red", "neutrals")
        },
        "trig": {
            k: []
            for k in (
                "actions",
                "events",
                "custom",
                "func",
                "flag",
                "conditions",
                "customStartup",
                "funcStartup",
            )
        },
        "triggers": {"zones": []},
        "result": {
            "total": 0,
            "offline": empty_result,
            "blue": empty_result,
            "red": empty_result,
        },
        "groundControl": {
            "isPilotControlVehicles": False,
            "roles": {},
            "passwords": {},
        },
        "goals": [],
        "failures": [],
        "forcedOptions": [],
        "trigrules": [],
        "requiredModules": [],
        "pictureFileNameR": [],
        "pictureFileNameB": [],
        "pictureFileNameN": [],
        "pictureFileNameServer": [],
        "maxDictId": len(DICT_KEYS),
        "currentKey": 0,
    }
    dictionary = {}
    for i, key in enumerate(DICT_KEYS, 1):
        mission[key] = f"DictKey_{key}_{i}"
        dictionary[f"DictKey_{key}_{i}"] = ""
    return mission, dictionary


def miz_files(
    mission: dict[str, Any],
    dictionary: dict[str, str],
    warehouses: dict[str, Any] | None = None,
) -> dict[str, str]:
    """``{zip entry name: text}`` of a mission table, its dictionary and its
    ``warehouses`` (default none)."""
    return {
        "mission": _assignment("mission", mission),
        "warehouses": _assignment(
            "warehouses", warehouses or {"airports": [], "warehouses": []}
        ),
        "theatre": mission["theatre"],
        "l10n/DEFAULT/dictionary": _assignment("dictionary", dictionary),
        "l10n/DEFAULT/mapResource": _assignment("mapResource", {}),
    }


def mission_files(theatre: str, defaults: dict[str, Any]) -> dict[str, str]:
    """``{zip entry name: text}`` of the empty mission on ``theatre``."""
    return miz_files(*empty_mission(theatre, defaults))


def write_miz(path: Path, files: dict[str, str]) -> None:
    """Write ``files`` as a deterministic zip (entry order as given)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, text.encode("utf-8"))
