"""Extract ``Entity.ThreatSystem`` records: everything DCS puts on an RWR, plus
the air defence systems that fire without a radar.

Ground systems (``sam``, ``aaa``) are built from ``Air Defence`` units:

* launchers are the units whose weapon systems fire a missile (a weapon of
  category ``wsType_Missile``) or gun ammunition;
* two launchers are one system when they fire a common missile, when one
  depends on the other, or when both depend directly on one unit (``WS[i].LN[j]
  .depends_on_unit``); units reached only through further dependencies (a
  search radar serving several track radars) are shared, not merged;
* a system's components are its launchers, the units that depend directly on
  a launcher or on a unit a launcher depends on directly (e.g. the SA-2's
  alternative track radar), and every unit those depend on, transitively;
* a system that fires a missile is ``sam``; a gun-only system is ``aaa`` and is
  kept only when a component carries a ``SAM SR``/``SAM TR`` attribute or is on
  the RWR (radar-directed guns);
* an RWR-listed ``Air Defence`` unit in no system is a system of its own
  (``ewr`` when it carries the ``EWR`` attribute).

``id``: a ``sam`` system's lexicographically smallest missile name (launchers
sharing a missile are one system, so a missile names one system); otherwise the
smallest unit type among its launchers, or the emitter unit type. Ships and
aircraft on the RWR are ``ship``/``aircraft`` entries keyed by their unit type.

``natoDesignation`` (``SA-11``; ``Patriot`` for a western system) is the one
name a threat's naming units carry: its launchers (the components with
``weapons`` or ``gunAmmo``) and ``SAM TR`` components, or the single component
or emitter. A unit's name is its ``threats/natoDesignation`` overlay entry
(keyed by unit type), else the one DCS's NATO speech protocol calls it by (the
install's ``Scripts/Speech/NATO.lua``, ``displayTypeIds`` ->
``displayTypeName``): the overlay fills units NATO.lua does not name and
overrides radio callouts that are not formal names (``MANPADS``, ``Zeus``).
The name is ``hand-authored`` unless a naming unit takes it from NATO.lua.
Naming units that disagree leave the threat unnamed (a warning). An overlay
entry that names no threat or repeats NATO.lua's name, and a NATO.lua unit
type no ``db/Units`` record defines and the
``threats/natoDesignationUpstreamGaps`` overlay does not list (or lists but is
defined), stop the extraction.

A system has one component per unit. ``roles`` are the unit's ``SAM
SR/TR/LL/CC/AUX``, ``AAA`` and ``EWR`` attributes only (possibly none, e.g. a
Chaparral launcher); being a launcher is what ``weapons`` (missiles, with
their ``envelope``) and ``gunAmmo`` (with ``gunEnvelope``) say.
``rwrSymbol``/``alic`` (see ``rwr``) and ``requires`` are the unit's own.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .common import HAND_AUTHORED, assign_defined, fail, read_text, warn
from .extract_units import AIRCRAFT_DIRS
from .lua_reader import (
    array_entries,
    as_number,
    km,
    lua_to_py,
    sandbox_exec,
    strings_of,
)
from .overlays import Overlays
from .rwr import RwrJoin

AIR_DEFENCE = "Air Defence"
MISSILE = "wsType_Missile"
SAM_ROLES = ("SAM SR", "SAM TR", "SAM LL", "SAM CC", "SAM AUX")
ROLES = (*SAM_ROLES, "AAA", "EWR")
SHIPS = "Ships"
NATO_SPEECH = Path("Scripts/Speech/NATO.lua")


def _table_at(text: str, pattern: str, where: str) -> str:
    """The Lua table constructor that starts where ``pattern`` ends."""
    m = re.search(pattern, text)
    if m is None or not m.group().endswith("{"):
        fail(f"{where}: no {pattern!r}")
    depth = 0
    i = start = m.end() - 1
    while i < len(text):
        c = text[i]
        if c in "'\"":
            i += 1
            while i < len(text) and text[i] != c:
                i += 2 if text[i] == "\\" else 1
        elif text.startswith("--", i):
            i = text.find("\n", i)
            if i < 0:
                break
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    fail(f"{where}: unterminated table after {pattern!r}")


def nato_names(install_dir: Path) -> dict[str, str]:
    """Unit type -> the name the NATO speech protocol calls an air defence unit
    by: ``displayTypeIds[type]`` indexes ``displayTypeName``'s phrases."""
    path = install_dir / NATO_SPEECH
    try:
        text = read_text(path)
    except FileNotFoundError:
        fail(f"no {NATO_SPEECH} in {install_dir}")
    ids = _table_at(text, r"displayTypeIds\s*=\s*\{", str(path))
    phrases = _table_at(text, r"displayTypeName\s*=\s*Phrases:new\(\s*\{", str(path))
    ok, env = sandbox_exec(
        f"local _ = function(s) return s end\nids = {ids}\nphrases = {phrases}\n",
        str(path),
    )
    if not ok:
        fail(f"{path}: {env}")
    by_id = {i: p[1] for i, p in enumerate(lua_to_py(env["phrases"]), 1)}
    out: dict[str, str] = {}
    for unit, i in sorted(lua_to_py(env["ids"]).items()):
        if i not in by_id:
            fail(f"{path}: displayTypeIds[{unit!r}] = {i} names no phrase")
        out[unit] = by_id[i]
    return out


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        value = list(value.values())
    return [s for v in value for s in _strings(v)] if isinstance(value, list) else []


def depends_on(rec: dict[str, Any], uid: str) -> list[Any]:
    """The alternatives of the unit's ``WS[i].LN[j].depends_on_unit`` tables,
    in WS/LN order without repeats, each exactly as DCS writes it."""
    out: list[Any] = []
    for ws in array_entries(rec.get("WS"), mixed=True):
        for ln in array_entries(ws.get("LN") if isinstance(ws, dict) else None):
            value = ln.get("depends_on_unit") if isinstance(ln, dict) else None
            if value is None:
                continue
            if not isinstance(value, list):
                fail(f"{uid}: depends_on_unit {value!r} is not a list")
            out += [alt for alt in value if alt not in out]
    return out


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _closure(seeds: set[str], edges: Mapping[str, set[str]]) -> set[str]:
    out, todo = set(seeds), list(seeds)
    while todo:
        for nxt in edges.get(todo.pop(), ()):
            if nxt not in out:
                out.add(nxt)
                todo.append(nxt)
    return out


def _span(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The widest envelope of weapon-system entries: max range/altitude, min
    minimums."""
    out: dict[str, Any] = {}
    for key, pick in (("rMaxKm", max), ("rMinKm", min), ("hMaxM", max), ("hMinM", min)):
        values = [e[key] for e in entries if e.get(key) is not None]
        if values:
            out[key] = pick(values)
    return out


def _missile_envelope(
    names: list[str], rockets: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    entries = []
    for name in names:
        raw = rockets.get(name, {})
        entries.append(
            {
                "rMaxKm": km(raw.get("D_max")),
                "rMinKm": km(raw.get("D_min")),
                "hMaxM": as_number(raw.get("H_max")),
                "hMinM": as_number(raw.get("H_min")),
            }
        )
    return _span(entries)


def build_threats(
    units: Mapping[str, dict[str, Any]],
    unit_dirs: Mapping[str, str],
    unit_sensors: Mapping[str, list[str]],
    sensor_kinds: Mapping[str, str],
    unit_systems: Mapping[str, list[dict[str, Any]]],
    weapons: Mapping[str, dict[str, Any]],
    rockets: Mapping[str, dict[str, Any]],
    rwr: RwrJoin,
    nato: Mapping[str, str],
    overlays: Overlays,
) -> dict[str, dict[str, Any]]:
    """``units``: raw unit records by type; ``unit_dirs``: type -> its
    ``db/Units`` dir (``Cars``, ``Ships``, ``Planes``, ...); ``unit_systems``:
    type -> its ``Entity.WeaponSystem`` entries (``extract_units.build_surface``);
    ``rockets``: raw missile records by name (envelope fallback); ``nato``:
    unit type -> NATO speech name (``nato_names``)."""
    air_defence = {u: r for u, r in units.items() if r.get("category") == AIR_DEFENCE}
    attrs = {u: set(strings_of(r.get("attribute"))) for u, r in air_defence.items()}
    needs = {
        u: {s for d in depends_on(r, u) for s in _strings(d)} & air_defence.keys() - {u}
        for u, r in air_defence.items()
    }
    requires = {u: depends_on(r, u) for u, r in air_defence.items()}
    systems_of = {u: unit_systems.get(u, []) for u in air_defence}
    missiles = {
        u: sorted(
            {
                w
                for ws in systems
                for w in ws.get("weapons", [])
                if weapons[w].get("categoryName") == MISSILE
            }
        )
        for u, systems in systems_of.items()
    }
    guns = {u: [ws for ws in s if ws.get("gunAmmo")] for u, s in systems_of.items()}
    launchers = sorted(u for u in air_defence if missiles[u] or guns[u])

    groups = _Union()
    by_missile: dict[str, str] = {}
    by_need: dict[str, str] = {}
    for u in launchers:
        groups.find(u)
        for m in missiles[u]:
            groups.union(u, by_missile.setdefault(m, u))
        for n in needs[u]:
            groups.union(u, by_need.setdefault(n, u))
            if n in launchers:
                groups.union(u, n)
    grouped: dict[str, list[str]] = {}
    for u in launchers:
        grouped.setdefault(groups.find(u), []).append(u)

    emitters = {**rwr.units}
    threats: dict[str, dict[str, Any]] = {}
    placed: set[str] = set()

    def add(threat: dict[str, Any]) -> None:
        if threat["id"] in threats:
            fail(f"threat id {threat['id']!r} names two threats")
        threats[threat["id"]] = threat

    def components(members: set[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for uid in sorted(members):
            c: dict[str, Any] = {
                "unit": uid,
                "roles": [r for r in ROLES if r in attrs[uid]],
            }
            assign_defined(c, emitters.get(uid, {}))
            if missiles[uid]:
                entries = [
                    ws
                    for ws in systems_of[uid]
                    if set(ws.get("weapons", [])) & set(missiles[uid])
                ]
                c["weapons"] = missiles[uid]
                envelope = {
                    **_missile_envelope(missiles[uid], rockets),
                    **_span(entries),
                }
                if "rMaxKm" in envelope:
                    c["envelope"] = envelope
            if guns[uid]:
                c["gunAmmo"] = sorted({a for ws in guns[uid] for a in ws["gunAmmo"]})
                envelope = _span(guns[uid])
                if "rMaxKm" in envelope:
                    c["gunEnvelope"] = envelope
            if requires[uid]:
                c["requires"] = requires[uid]
            out.append(c)
        return out

    def sensors(members: set[str]) -> list[str]:
        return sorted({s for u in members for s in unit_sensors.get(u, [])})

    for root in sorted(grouped):
        group = grouped[root]
        direct = set(group).union(*(needs[u] for u in group))
        peers = {v for v, n in needs.items() if n & direct}
        members = _closure(set(group) | peers, needs)
        fired = {m for u in group for m in missiles[u]}
        if not fired and not any(
            attrs[u] & {"SAM SR", "SAM TR"} or u in emitters for u in members
        ):
            continue  # guns without a radar
        threat: dict[str, Any] = {
            "id": min(fired) if fired else min(group),
            "kind": "sam" if fired else "aaa",
            "components": components(members),
        }
        assign_defined(threat, {"sensors": sensors(members) or None})
        add(threat)
        placed |= members

    for uid in sorted(emitters):
        if uid in placed:
            continue
        where = unit_dirs.get(uid)
        entry: dict[str, Any] = {"id": uid, "unit": uid}
        if uid in air_defence and "EWR" in attrs[uid]:
            entry["kind"] = "ewr"
            assign_defined(entry, {"sensors": unit_sensors.get(uid) or None})
        elif uid in air_defence:
            if not attrs[uid] & set(ROLES):
                fail(f"RWR emitter {uid!r} has none of {ROLES}")
            kind = "sam" if attrs[uid] & set(SAM_ROLES) else "aaa"
            threat = {"id": uid, "kind": kind, "components": components({uid})}
            assign_defined(threat, {"sensors": sensors({uid}) or None})
            add(threat)
            continue
        elif where == SHIPS:
            entry["kind"] = "ship"
        elif where in AIRCRAFT_DIRS:
            entry["kind"] = "aircraft"
            radars = [
                s for s in unit_sensors.get(uid, []) if sensor_kinds.get(s) == "radar"
            ]
            assign_defined(entry, {"sensors": radars or None})
        else:
            warn(
                f"RWR emitter {uid!r} ({where}) is not Air Defence, a ship or an aircraft; skipped"
            )
            continue
        entry.update(emitters[uid])
        add(entry)

    name_threats(threats, units, nato, overlays)
    return threats


def _naming_units(threat: dict[str, Any]) -> list[str]:
    """The units a threat takes its name from: its launchers and track radars,
    or its single component or emitter."""
    if "unit" in threat:
        return [threat["unit"]]
    components = threat["components"]
    if len(components) == 1:
        return [components[0]["unit"]]
    return [
        c["unit"]
        for c in components
        if c.get("weapons") or c.get("gunAmmo") or "SAM TR" in c["roles"]
    ]


def name_threats(
    threats: Mapping[str, dict[str, Any]],
    units: Mapping[str, Any],
    nato: Mapping[str, str],
    overlays: Overlays,
) -> None:
    """Set each threat's ``natoDesignation`` (see the module docstring)."""
    hand = overlays.table("threats", "natoDesignation")
    gaps = overlays.table("threats", "natoDesignationUpstreamGaps")
    naming = {u for t in threats.values() for u in _naming_units(t)}
    stale = [
        *(
            f"NATO.lua names unit type {u!r} that no db/Units record defines"
            for u in sorted(set(nato) - units.keys() - gaps.keys())
        ),
        *(
            f"threats/natoDesignationUpstreamGaps {u!r} is now a unit type"
            for u in sorted(gaps.keys() & units.keys())
        ),
        *(
            f"threats/natoDesignationUpstreamGaps {u!r} is not in NATO.lua"
            for u in sorted(gaps.keys() - nato.keys())
        ),
        *(
            f"threats/natoDesignation {u!r}: NATO.lua already names it {nato[u]!r}"
            for u in sorted(hand.keys() & nato.keys())
            if hand[u] == nato[u]
        ),
        *(
            f"threats/natoDesignation {u!r}: no threat takes its name from this unit"
            for u in sorted(hand.keys() - naming)
        ),
    ]
    if stale:
        fail("stale NATO name entries: " + "; ".join(stale))

    conflicts: list[str] = []
    for tid, threat in threats.items():
        found = {
            u: hand.get(u) or nato[u]
            for u in _naming_units(threat)
            if u in nato or u in hand
        }
        names = set(found.values())
        if len(names) > 1:
            conflicts.append(f"{tid} {dict(sorted(found.items()))}")
        elif names:
            threat["natoDesignation"] = names.pop()
            if not found.keys() & (nato.keys() - hand.keys()):
                threat["_source"] = {"natoDesignation": HAND_AUTHORED}
    if conflicts:
        warn(
            f"threat(s) whose units have different NATO names; left unnamed: {conflicts}"
        )
    unnamed = sorted(
        t
        for t, r in threats.items()
        if r["kind"] in ("sam", "aaa") and "natoDesignation" not in r
    )
    if unnamed:
        warn(f"{len(unnamed)} sam/aaa threat(s) without a natoDesignation: {unnamed}")


def unit_dirs(by_category: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """Unit type -> its ``db/Units`` dir."""
    return {u: d for d, recs in by_category.items() for u in recs}


def summary(threats: Mapping[str, dict[str, Any]]) -> str:
    kinds: dict[str, int] = {}
    for t in threats.values():
        kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
    return f"Threats by kind: {dict(sorted(kinds.items()))}"
