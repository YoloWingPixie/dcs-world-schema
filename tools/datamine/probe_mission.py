"""The argument probe's mission: the empty mission (``terrain_mission``)
populated from ``overlays.yaml`` ``probe/mission`` (format documented there).

For each coalition, in the overlay's order (blue, then red, per object): the
objects as mission editor groups (planes, helicopters and the client slot
airborne at their first waypoint, vehicles, ships, statics with FARPs and
cargo among them) in the side's country; the side's airbase warehouse with
the overlay's stock; then the trigger zones, the map drawing (layer
``Common``) and a mission-start trigger whose script sets the flags and makes
the F10 marks (a .miz holds neither). Group and unit ids count up from 1 in
that order, so the mission is deterministic.

The first waypoint of every AI group but ``fires`` ones sets ROE weapon hold
(``fires`` aircraft: open fire, so they attack only what they are tasked
with); aircraft are also immortal and invisible and orbit there, ``immortal``
vehicles immortal. ``spec`` reads the DCS values the overlay names from the
reference data (``reference_dir``): the ROE option and values from the
scripting API dump's ``AI.Option`` (``roe``), an aircraft's ``fuel:
internal`` and ``speed: optimal`` from the aircraft series. An object may be placed for some ``sides`` only, and at
the anchors of ``anchorSide`` rather than its own side's; aircraft carry
``pylons`` (station -> CLSID). ``build`` returns
the ``.miz`` files, ``pools``: the names and ids the probe's context samples
draw from (``probe/contextSamples``; ``POOLS``), and ``samples``: the objects
probe-call.lua's setupMission uses. ``extra`` groups (``Extra``; the actions
probe's) follow for blue: late-activated copies of an object's group with
their own name, place, first-waypoint tasks and further waypoints.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.package.lua_data import lua_string

from . import overlays as overlays_mod
from .common import (
    API_DIR,
    LATEST,
    REFERENCE_DATA_DIR,
    fail,
    load_json,
    load_series,
)
from .terrain_mission import empty_mission, miz_files

SERIES, TABLE = "probe", "mission"
SIDES = ("blue", "red")
SIDE_IDS = {"red": 1, "blue": 2}
POOLS = (
    "groups",
    "units",
    "statics",
    "zones",
    "airbases",
    "drawings",
    "flags",
    "unitTypes",
    "staticTypes",
    "sides",
    "countries",
)
# Mission editor group categories of the overlay's kinds.
CATEGORIES = {
    "plane": "plane",
    "client": "plane",
    "helicopter": "helicopter",
    "vehicle": "vehicle",
    "ship": "ship",
    "static": "static",
}
AIR = {"plane", "client", "helicopter"}
# The scripting API's ``AI.Option`` domain of each AI object kind.
DOMAINS = {
    "plane": "Air",
    "client": "Air",
    "helicopter": "Air",
    "vehicle": "Ground",
    "ship": "Naval",
}
ROE_ROLES = ("hold", "fires")
# Aircraft values an object may name instead of giving a number: ``fuel``
# from the aircraft series' ``aero.internalFuelKg``, ``speed`` from its
# ``performance.vOptMs``.
FROM_AIRCRAFT = {
    "fuel": ("internal", ("aero", "internalFuelKg")),
    "speed": ("optimal", ("performance", "vOptMs")),
}
SAMPLE_KEYS = {"airbase", "air", "ground", "arty", "static", "target"}
ROLES = (
    "Observer",
    "ForwardObserver",
    "ArtilleryCommander",
    "Instructor",
    "Spectrator",
    "Pilot",
)
LAYERS = ("Red", "Blue", "Neutral", "Common", "Author")


def _action(id_: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"id": "WrappedAction", "params": {"action": {"id": id_, "params": params}}}


IMMORTAL = _action("SetImmortal", {"value": True})
INVISIBLE = _action("SetInvisible", {"value": True})


@dataclass(frozen=True)
class Mission:
    files: dict[str, str]
    pools: dict[str, list[Any]]
    samples: dict[str, Any]

    @property
    def id(self) -> str:
        """SHA-256 (16 hex digits) of the mission's files."""
        h = hashlib.sha256()
        for name, text in self.files.items():
            h.update(name.encode() + b"\0" + text.encode() + b"\0")
        return h.hexdigest()[:16]


def reference_dir() -> Path:
    """The reference data the probe missions read DCS values from:
    ``dcs-world-reference/latest`` (a version not extracted yet reads the
    previous one's)."""
    latest = REFERENCE_DATA_DIR / LATEST
    if not latest.is_dir():
        fail(f"no reference data in {latest}")
    return latest


def _api_table(node: dict[str, Any], path: list[str], where: str) -> dict[str, Any]:
    for key in path:
        members = {
            m["key"]: m.get("value") or {}
            for m in node.get("members") or []
            if m.get("keyType") == "string"
        }
        if key not in members:
            fail(f"{where}: no {'.'.join(path)} in the API dump")
        node = members[key]
    return node


def _api_number(node: dict[str, Any], path: list[str], where: str) -> int:
    value = _api_table(node, path, where)
    if value.get("type") != "number":
        fail(f"{where}: {'.'.join(path)} is no number in the API dump")
    return int(value["value"])


def resolve_roe(names: dict[str, str]) -> dict[str, dict[str, Any]]:
    """``{domain: {role: Option action}}`` of the overlay's ``roe`` value
    names (``AI.Option.<domain>.val.ROE.<name>``, option number
    ``AI.Option.<domain>.id.ROE``) from the scripting API dump of
    ``reference_dir()``."""
    data_dir = reference_dir()
    where = f"overlays {SERIES}/{TABLE} roe"
    if sorted(names) != sorted(ROE_ROLES):
        fail(f"{where}: needs exactly {', '.join(ROE_ROLES)}")
    dump = load_json(data_dir / API_DIR / "scripting.json")
    ai = (dump.get("globals") or {}).get("AI")
    if not isinstance(ai, dict):
        fail(f"{where}: no AI in the API dump of {data_dir.name}")
    g = _api_table(ai, ["Option"], where)
    out: dict[str, dict[str, Any]] = {}
    for domain in sorted(set(DOMAINS.values())):
        option = _api_number(g, [domain, "id", "ROE"], where)
        out[domain] = {
            role: _action(
                "Option",
                {
                    "name": option,
                    "value": _api_number(g, [domain, "val", "ROE", name], where),
                },
            )
            for role, name in names.items()
        }
    return out


def resolve_objects(objects: list[dict[str, Any]], where: str) -> list[dict[str, Any]]:
    """``objects`` with each aircraft's ``fuel: internal`` and ``speed:
    optimal`` (``FROM_AIRCRAFT``) read from the aircraft series of
    ``reference_dir()``, per side when its ``type`` is; any other
    aircraft value must be a number."""
    data_dir = reference_dir()
    aircraft: dict[str, dict[str, Any]] = {}

    def value(obj: dict[str, Any], type_: str, key: str) -> float:
        path = FROM_AIRCRAFT[key][1]
        node: Any = aircraft.get(type_)
        for p in path:
            node = node.get(p) if isinstance(node, dict) else None
        if not isinstance(node, (int, float)):
            fail(
                f"{where} {obj['name']}: aircraft {type_} has no {'.'.join(path)} "
                f"in {data_dir.name}; give {key} as a number"
            )
        return node

    out = []
    for obj in objects:
        obj = dict(obj)
        for key, (word, _) in FROM_AIRCRAFT.items():
            if obj.get(key) != word:
                continue
            if obj["kind"] not in AIR:
                fail(f"{where} {obj['name']}: {key}: {word} is for aircraft")
            if not aircraft:
                series = load_series(data_dir, "aircraft", required=True)
                aircraft.update({r["id"]: r for r in series.values()})
            types = obj["type"]
            obj[key] = (
                {s: value(obj, t, key) for s, t in types.items()}
                if isinstance(types, dict)
                else value(obj, types, key)
            )
        if obj["kind"] in AIR:
            for key in FROM_AIRCRAFT:
                if not all(
                    isinstance(per_side(obj.get(key), s), (int, float)) for s in SIDES
                ):
                    fail(
                        f"{where} {obj['name']}: an aircraft needs {key} "
                        f"({FROM_AIRCRAFT[key][0]} or a number)"
                    )
        out.append(obj)
    return out


def spec(version: str | None = None) -> dict[str, Any]:
    """The ``probe/mission`` overlay table, its DCS values resolved from
    ``reference_dir()``: ``roe`` (``resolve_roe``) and the objects'
    aircraft values (``resolve_objects``)."""
    value = overlays_mod.load(version).table(SERIES, TABLE)
    where = f"overlays {SERIES}/{TABLE}"
    if not isinstance(value, dict):
        fail(f"{where}: a mapping")
    for key in (
        "theatre",
        "radioMHz",
        "roe",
        "sides",
        "objects",
        "warehouse",
        "samples",
    ):
        if key not in value:
            fail(f"{where}: missing {key}")
    if sorted(value["sides"]) != sorted(SIDES):
        fail(f"{where}: sides must be {', '.join(SIDES)}")
    check_objects(value["objects"], where)
    unknown = set(value["samples"]) - SAMPLE_KEYS
    if unknown:
        fail(f"{where}: unknown samples keys {sorted(unknown)}")
    return {
        **value,
        "roe": resolve_roe(value["roe"]),
        "objects": resolve_objects(value["objects"], where),
    }


def check_objects(objects: list[dict[str, Any]], where: str) -> None:
    for obj in objects:
        what = f"{where} {obj.get('name')}"
        if obj.get("kind") not in CATEGORIES:
            fail(f"{what}: kind must be one of {', '.join(CATEGORIES)}")
        if not set(obj.get("sides", SIDES)) <= set(SIDES):
            fail(f"{what}: sides must be some of {', '.join(SIDES)}")
        if obj.get("anchorSide", SIDES[0]) not in SIDES:
            fail(f"{what}: anchorSide must be one of {', '.join(SIDES)}")


def per_side(value: Any, side: str) -> Any:
    """``value`` for ``side``: its entry when given per side."""
    return value[side] if isinstance(value, dict) else value


def anchored(s: dict[str, Any], side: str, item: dict[str, Any]) -> tuple[float, float]:
    """Where ``item`` (its ``anchor`` and ``offset``) lies for ``side``."""
    x, y = s["sides"][item.get("anchorSide") or side][item["anchor"]]
    dx, dy = item.get("offset") or (0, 0)
    return x + dx, y + dy


def fire_tasks(s: dict[str, Any], obj: dict[str, Any]) -> list[dict[str, Any]]:
    """First-waypoint ROE of an AI object (``s["roe"]`` of its domain):
    weapon hold unless it ``fires`` (then aircraft open fire: only at what
    they are tasked with)."""
    roe = s["roe"][DOMAINS[obj["kind"]]]
    if not obj.get("fires"):
        return [roe["hold"]]
    return [roe["fires"]] if obj["kind"] in AIR else []


def combo(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """A ``ComboTask`` of ``tasks`` in order, each enabled."""
    return {
        "id": "ComboTask",
        "params": {
            "tasks": [
                {"number": i, "auto": False, "enabled": True, **t}
                for i, t in enumerate(tasks, 1)
            ]
        },
    }


def _waypoint(
    x: float,
    y: float,
    alt: float,
    speed: float,
    action: str,
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "alt": alt,
        "alt_type": "BARO",
        "type": "Turning Point",
        "action": action,
        "speed": speed,
        "speed_locked": True,
        "ETA": 0,
        "ETA_locked": True,
        "formation_template": "",
        "task": combo(tasks),
    }


def _callsign(base: Any, n: int) -> Any:
    if isinstance(base, int):
        return base + n
    return {1: 1, 2: n, 3: 1, "name": f"{base}{n}1"}


class _Builder:
    def __init__(self, s: dict[str, Any]) -> None:
        self.s = s
        self.group_id = self.unit_id = 0
        self.flights = dict.fromkeys(SIDES, 0)
        self.pools: dict[str, list[Any]] = {k: [] for k in POOLS}
        self.countries: dict[str, dict[str, Any]] = {}
        for side in SIDES:
            c = s["sides"][side]["country"]
            self.countries[side] = {"id": c["id"], "name": c["name"]}

    def _add(self, pool: str, value: Any) -> None:
        if value not in self.pools[pool]:
            self.pools[pool].append(value)

    def place(self, obj: dict[str, Any], side: str, extra: Extra | None = None) -> None:
        kind = obj["kind"]
        name = extra.name if extra else f"{obj['name']}_{side.upper()}"
        type_ = per_side(obj["type"], side)
        x, y = extra.at if extra else anchored(self.s, side, obj)
        self.group_id += 1
        self.unit_id += 1
        if kind == "static":
            group = self._static(obj, name, type_, x, y)
            self._add("statics", name)
            self._add("staticTypes", type_)
            if obj.get("category") == "Heliports":
                self._add("airbases", name)
        else:
            unit = f"{name}-1"
            if kind in AIR:
                group = self._air(obj, side, name, unit, type_, x, y)
            elif kind == "ship":
                group = self._ship(obj, name, unit, type_, x, y)
            else:
                group = self._vehicle(obj, name, unit, type_, x, y)
            if extra:
                _extra_route(group, extra)
            else:
                if kind == "ship":
                    self._add("airbases", unit)
                self._add("groups", name)
                self._add("units", unit)
                self._add("unitTypes", type_)
        category = CATEGORIES[kind]
        self.countries[side].setdefault(category, {"group": []})["group"].append(group)

    def _air(
        self,
        obj: dict[str, Any],
        side: str,
        name: str,
        unit: str,
        type_: str,
        x: float,
        y: float,
    ) -> dict[str, Any]:
        alt = obj["alt"]
        speed = per_side(obj["speed"], side)
        client = obj["kind"] == "client"
        self.flights[side] += 1
        tasks = (
            []
            if client
            else [
                *fire_tasks(self.s, obj),
                IMMORTAL,
                INVISIBLE,
                {
                    "id": "Orbit",
                    "params": {"pattern": "Circle", "altitude": alt, "speed": speed},
                },
            ]
        )
        return {
            "name": name,
            "groupId": self.group_id,
            "task": "Nothing",
            "x": x,
            "y": y,
            "start_time": 0,
            "hidden": False,
            "uncontrolled": False,
            "communication": True,
            "radioSet": False,
            "frequency": self.s["radioMHz"],
            "modulation": 0,
            "tasks": {},
            "route": {"points": [_waypoint(x, y, alt, speed, "Turning Point", tasks)]},
            "units": [
                {
                    "name": unit,
                    "unitId": self.unit_id,
                    "type": type_,
                    "skill": "Client" if client else "Average",
                    "x": x,
                    "y": y,
                    "alt": alt,
                    "alt_type": "BARO",
                    "speed": speed,
                    "heading": 0,
                    "psi": 0,
                    "onboard_num": f"{self.unit_id:03d}",
                    "callsign": _callsign(
                        self.s["sides"][side]["callsign"], self.flights[side]
                    ),
                    "payload": {
                        "fuel": per_side(obj["fuel"], side),
                        "flare": 0,
                        "chaff": 0,
                        "gun": 100,
                        "pylons": {
                            int(n): {"CLSID": clsid}
                            for n, clsid in (obj.get("pylons") or {}).items()
                        },
                    },
                }
            ],
        }

    def _vehicle(
        self, obj: dict[str, Any], name: str, unit: str, type_: str, x: float, y: float
    ) -> dict[str, Any]:
        tasks = fire_tasks(self.s, obj)
        if obj.get("immortal"):
            tasks.append(IMMORTAL)
        return {
            "name": name,
            "groupId": self.group_id,
            "task": "Ground Nothing",
            "x": x,
            "y": y,
            "start_time": 0,
            "hidden": False,
            "visible": False,
            "uncontrollable": False,
            "tasks": {},
            "route": {
                "spans": [],
                "points": [_waypoint(x, y, 0, 0, "Off Road", tasks)],
            },
            "units": [
                {
                    "name": unit,
                    "unitId": self.unit_id,
                    "type": type_,
                    "skill": "Average",
                    "x": x,
                    "y": y,
                    "heading": 0,
                    "playerCanDrive": False,
                }
            ],
        }

    def _ship(
        self, obj: dict[str, Any], name: str, unit: str, type_: str, x: float, y: float
    ) -> dict[str, Any]:
        return {
            "name": name,
            "groupId": self.group_id,
            "x": x,
            "y": y,
            "start_time": 0,
            "hidden": False,
            "visible": False,
            "uncontrollable": False,
            "tasks": {},
            "route": {
                "points": [
                    _waypoint(x, y, 0, 0, "Turning Point", fire_tasks(self.s, obj))
                ]
            },
            "units": [
                {
                    "name": unit,
                    "unitId": self.unit_id,
                    "type": type_,
                    "skill": "Average",
                    "x": x,
                    "y": y,
                    "heading": 0,
                    "frequency": 127500000,
                    "modulation": 0,
                }
            ],
        }

    def _static(
        self, obj: dict[str, Any], name: str, type_: str, x: float, y: float
    ) -> dict[str, Any]:
        return {
            "name": name,
            "groupId": self.group_id,
            "x": x,
            "y": y,
            "heading": 0,
            "dead": False,
            "hidden": False,
            "route": {
                "points": [
                    {
                        "x": x,
                        "y": y,
                        "alt": 0,
                        "type": "",
                        "name": "",
                        "speed": 0,
                        "formation_template": "",
                        "action": "",
                    }
                ]
            },
            "units": [
                {
                    "name": name,
                    "unitId": self.unit_id,
                    "type": type_,
                    "category": obj["category"],
                    "x": x,
                    "y": y,
                    "heading": 0,
                    "rate": 100,
                    **(obj.get("unit") or {}),
                }
            ],
        }


@dataclass(frozen=True)
class Extra:
    """A late-activated group added after the overlay's objects (the actions
    probe's route groups): a copy of an object's group named ``name`` at
    ``at`` ([x, y] m), whose first waypoint's tasks are ``tasks`` and whose
    route goes on to ``points`` ([x, y] each)."""

    name: str
    at: tuple[float, float]
    tasks: list[dict[str, Any]]
    points: tuple[tuple[float, float], ...] = ()
    speed: float | None = None  # every waypoint's, when given


def _extra_route(group: dict[str, Any], extra: Extra) -> None:
    group["lateActivation"] = True
    first = group["route"]["points"][0]
    first["task"] = combo(extra.tasks)
    if extra.speed is not None:
        first["speed"] = extra.speed
    for x, y in extra.points:
        group["route"]["points"].append({**first, "x": x, "y": y, "task": combo([])})


def _zone(s: dict[str, Any], i: int, z: dict[str, Any]) -> dict[str, Any]:
    x, y = anchored(s, z["side"], z)
    zone = {
        "name": z["name"],
        "zoneId": i,
        "x": x,
        "y": y,
        "heading": 0,
        "hidden": False,
        "color": [1, 1, 1, 0.15],
        "properties": {},
    }
    if "quad" in z:
        corners = [(x + dx, y + dy) for dx, dy in z["quad"]]
        if len(corners) != 4:
            fail(f"overlays {SERIES}/{TABLE} zone {z['name']}: a quad has 4 corners")
        zone["type"] = 2
        zone["verticies"] = [{"x": cx, "y": cy} for cx, cy in corners]
        zone["radius"] = max(math.hypot(cx - x, cy - y) for cx, cy in corners)
    else:
        zone["type"] = 0
        zone["radius"] = z["radius"]
    return zone


def _drawings(s: dict[str, Any]) -> dict[str, Any]:
    objects = []
    for d in s.get("drawings") or []:
        x, y = anchored(s, d["side"], d)
        objects.append(
            {
                "name": d["name"],
                "primitiveType": "Polygon",
                "polygonMode": "circle",
                "radius": d["radius"],
                "mapX": x,
                "mapY": y,
                "layerName": "Common",
                "visible": True,
                "colorString": "0xff0000ff",
                "fillColorString": "0xff000040",
                "style": "solid",
                "thickness": 8,
            }
        )
    return {
        "layers": [
            {
                "name": name,
                "visible": True,
                "objects": objects if name == "Common" else [],
            }
            for name in LAYERS
        ],
        "options": {
            "hiddenOnF10Map": {
                role: {"Neutral": False, "Red": False, "Blue": False} for role in ROLES
            }
        },
    }


def start_script(s: dict[str, Any]) -> str:
    """The mission-start script: set the flags, make the marks."""
    lines = [
        f"trigger.action.setUserFlag({lua_string(str(name))}, {value})"
        for name, value in (s.get("flags") or {}).items()
    ]
    for m in s.get("marks") or []:
        x, y = anchored(s, m["side"], m)
        lines.append(
            f"trigger.action.markToAll({m['id']}, {lua_string(m['text'])}, "
            f"{{x = {x}, y = land.getHeight({{x = {x}, y = {y}}}), z = {y}}}, true)"
        )
    return "\n".join(lines)


def _start_trigger(mission: dict[str, Any], script: str) -> None:
    mission["trig"].update(
        actions=[f"a_do_script({lua_string(script)});"],
        conditions=["return(true)"],
        flag=[True],
        funcStartup=[
            "if mission.trig.conditions[1]() then mission.trig.actions[1]() end"
        ],
    )
    mission["trigrules"] = [
        {
            "predicate": "triggerStart",
            "comment": "PROBE_START",
            "eventlist": "",
            "rules": [],
            "actions": [{"predicate": "a_do_script", "text": script}],
        }
    ]


def _warehouses(s: dict[str, Any]) -> dict[str, Any]:
    w = s["warehouse"]
    fuel = {"InitFuel": w["fuel"]}
    airports = {}
    for side in SIDES:
        airports[s["sides"][side]["airbase"]["id"]] = {
            "coalition": side.upper(),
            "unlimitedMunitions": False,
            "unlimitedAircrafts": False,
            "unlimitedFuel": False,
            "jet_fuel": fuel,
            "gasoline": fuel,
            "methanol_mixture": fuel,
            "diesel": fuel,
            "weapons": list(w["weapons"]),
            "aircrafts": {
                "planes": {
                    t: {**v, "unlimited": False} for t, v in w["planes"].items()
                },
                "helicopters": {},
            },
            "suppliers": {},
            "size": 100,
            "periodicity": 30,
            "speed": 16.666666,
            "OperatingLevel_Air": 10,
            "OperatingLevel_Eqp": 10,
            "OperatingLevel_Fuel": 10,
            "allowHotStart": False,
            "dynamicCargo": False,
            "dynamicSpawn": False,
        }
    return {"airports": airports, "warehouses": {}}


def build(
    s: dict[str, Any],
    defaults: dict[str, Any] | None,
    extra: list[tuple[str, Extra]] | None = None,
) -> Mission:
    """The probe mission of overlay table ``s`` (``spec``) and the install's
    mission defaults (``terrain_mission.install_defaults``); without them
    only its pools and samples (no files). ``extra``: (object name,
    ``Extra``) groups placed for blue after the objects."""
    b = _Builder(s)
    for side in SIDES:
        b._add("airbases", s["sides"][side]["airbase"]["name"])
    for obj in s["objects"]:
        for side in SIDES:
            if side in obj.get("sides", SIDES):
                b.place(obj, side)
    objects = {o["name"]: o for o in s["objects"]}
    for obj_name, e in extra or []:
        if obj_name not in objects or objects[obj_name]["kind"] in ("static", "client"):
            fail(f"probe mission extra group {e.name}: no AI object {obj_name!r}")
        b.place(objects[obj_name], "blue", e)
    zones = [_zone(s, i, z) for i, z in enumerate(s.get("zones") or [], 1)]
    b.pools["zones"] = [z["name"] for z in zones]
    b.pools["drawings"] = [d["name"] for d in s.get("drawings") or []]
    b.pools["flags"] = [str(f) for f in s.get("flags") or {}]
    b.pools["sides"] = [SIDE_IDS[side] for side in SIDES]
    b.pools["countries"] = [s["sides"][side]["country"]["id"] for side in SIDES]
    samples = dict(s["samples"])
    for key, pool in (
        ("airbase", "airbases"),
        ("air", "groups"),
        ("ground", "groups"),
        ("arty", "groups"),
        ("static", "statics"),
    ):
        if samples.get(key) not in b.pools[pool]:
            fail(
                f"overlays {SERIES}/{TABLE}: samples {key} {samples.get(key)!r} "
                f"is none of the mission's {pool}"
            )
    if defaults is None:
        return Mission({}, b.pools, samples)
    mission, dictionary = empty_mission(s["theatre"], defaults)
    for side in SIDES:
        mission["coalition"][side]["country"] = [b.countries[side]]
        country_id = s["sides"][side]["country"]["id"]
        if country_id not in mission["coalitions"][side]:
            fail(
                f"overlays {SERIES}/{TABLE}: country {country_id} is not in the "
                f"install's default {side} coalition"
            )
    mission["triggers"] = {"zones": zones}
    mission["drawings"] = _drawings(s)
    _start_trigger(mission, start_script(s))
    return Mission(miz_files(mission, dictionary, _warehouses(s)), b.pools, samples)
