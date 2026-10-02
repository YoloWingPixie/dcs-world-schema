"""Extract ``Entity.Radio`` records from each flyable aircraft's ``panelRadio``
(else its ``HumanRadio``). DCS has no standalone radio entity, so ids are
``<aircraftType>__radio<index>``.

Each ``range`` segment keeps its bounds and one modulation, taken as the
mission editor does (MissionEditor/modules/me_panelRadio.lua):

1. the segment's ``modulation`` (a MODULATION_* number; ``HumanRadio`` radios
   without segments: ``HumanRadio.modulation``), with ``modulationDef`` as its
   ``defaultModulation``;
2. else the ``modulation`` label (``"AM"``, ``"FM"``) the radio's preset
   ``channels`` inside the segment show, as its MODULATION_<label> constant;
3. else MODULATION_AM, the editor's fallback for a segment without one
   (``updateModulation``; me_aircraft.lua ``fixRadio`` likewise).

``band`` is the band the radio's DCS ``name`` names (``UHF``, ``VHF``, ``HF``,
``V/UHF``; ``UHF`` and ``VHF`` together are ``V/UHF``); a radio whose name
names none gets the first ``radios/bandRules`` overlay rule its whole range
matches, stamped ``hand-authored``. ``guard`` (a segment covers a
``radios/guardMHz`` frequency of the band) and ``stepKHz``
(``radios/stepKHz``) are ``hand-authored``: DCS unit data has neither. An
unknown modulation, a segment whose channels show two labels, a name naming
conflicting bands, or a rule or band key that no radio uses stops the
extraction."""

from __future__ import annotations

import re
from typing import Any

from .common import HAND_AUTHORED, fail
from .dcs_constants import Constants
from .lua_reader import array_entries, as_dict, as_number, as_string
from .overlays import Overlays, rule, unused_keys, unused_rules

MODULATION = "Entity.RadioModulation"
FALLBACK_MODULATION = "MODULATION_AM"
# Band names as whole words of a radio name (Entity.RadioBand values).
_BAND_WORD = re.compile(r"(?<![A-Za-z0-9])(V/UHF|UHF|VHF|HF)(?![A-Za-z0-9])")


def _entries(value: Any) -> list[dict[str, Any]]:
    """A Lua array of tables, or a single table, as a list of dicts."""
    entries = array_entries(value) or ([value] if isinstance(value, dict) else [])
    return [e for e in entries if isinstance(e, dict)]


def named_band(name: str | None) -> str | None:
    """The band a radio name names, or None."""
    words = set(_BAND_WORD.findall(name or ""))
    if {"UHF", "VHF"} <= words:
        words = (words - {"UHF", "VHF"}) | {"V/UHF"}
    if len(words) > 1:
        fail(f"radio name {name!r} names bands {sorted(words)}")
    return next(iter(words), None)


class _Modulations:
    def __init__(self, constants: Constants) -> None:
        self.constants = constants

    def name(self, number: float, where: str) -> str:
        name = self.constants.name(MODULATION, number)
        if name is None:
            fail(f"{where}: modulation {number!r} is no DCS MODULATION constant")
        return name

    def number(self, name: str, where: str) -> int:
        number = self.constants.value("MODULATION", name)
        if number is None:
            fail(f"{where}: {name!r} is no DCS MODULATION constant")
        return int(number)

    def of_label(self, labels: set[str], where: str) -> int | None:
        if not labels:
            return None
        if len(labels) > 1:
            fail(f"{where}: preset channels show modulations {sorted(labels)}")
        return self.number(f"MODULATION_{next(iter(labels))}", where)


def _labels(
    channels: list[dict[str, Any]], lo: float, hi: float, where: str
) -> set[str]:
    """The ``modulation`` labels of the channels whose default is in [lo, hi]."""
    out = set()
    for c in channels:
        f = as_number(c.get("default"))
        label = c.get("modulation")
        if f is None or label is None or not lo <= f <= hi:
            continue
        if not isinstance(label, str):
            fail(f"{where}: channel modulation {label!r} is not a label")
        out.add(label)
    return out


def _segment(
    seg: dict[str, Any],
    lo: float,
    hi: float,
    channels: list[dict[str, Any]],
    mods: _Modulations,
    where: str,
) -> dict[str, Any]:
    m = as_number(seg.get("modulation"))
    if m is None:
        m = mods.of_label(_labels(channels, lo, hi, where), where)
    if m is None:
        m = mods.number(FALLBACK_MODULATION, where)
    out: dict[str, Any] = {
        "minMHz": lo,
        "maxMHz": hi,
        "modulation": int(m),
        "modulationName": mods.name(m, where),
    }
    d = as_number(seg.get("modulationDef"))
    if d is not None:
        out["defaultModulation"] = int(d)
        out["defaultModulationName"] = mods.name(d, where)
    return out


def _segments_of(
    rng: Any, channels: list[dict[str, Any]], mods: _Modulations, where: str
) -> list[dict[str, Any]]:
    out = []
    for seg in _entries(rng):
        lo, hi = as_number(seg.get("min")), as_number(seg.get("max"))
        if lo is not None and hi is not None:
            out.append(_segment(seg, lo, hi, channels, mods, where))
    return out


def _radios_of(
    atype: str, unit: dict[str, Any], mods: _Modulations
) -> list[tuple[int, str | None, list[dict[str, Any]], int]]:
    """(index, name, segments, preset count) per radio of one flyable unit."""
    radios = []
    for index, r in enumerate(_entries(unit.get("panelRadio"))):
        where = f"{atype} panelRadio[{index + 1}]"
        channels = _entries(r.get("channels"))
        segments = _segments_of(r.get("range"), channels, mods, where)
        if segments:
            radios.append((index, as_string(r.get("name")), segments, len(channels)))
    human = as_dict(unit.get("HumanRadio"))
    if not radios and human:
        where = f"{atype} HumanRadio"
        segments = _segments_of(human.get("rangeFrequency"), [], mods, where)
        if not segments:
            mn = as_number(human.get("minFrequency"))
            mx = as_number(human.get("maxFrequency"))
            freq = as_number(human.get("frequency"))
            if mn is not None and mx is not None:
                segments = [_segment(human, mn, mx, [], mods, where)]
            elif freq is not None:
                segments = [_segment(human, freq, freq, [], mods, where)]
        if segments:
            radios.append((0, None, segments, 0))
    return radios


def default_radio(
    atype: str, unit: dict[str, Any], constants: Constants
) -> dict[str, Any] | None:
    """``Entity.DefaultRadio`` from the unit's ``HumanRadio``; None without one."""
    human = unit.get("HumanRadio")
    if human is None:
        return None
    human = as_dict(human)
    where = f"{atype} HumanRadio"
    freq, mod = as_number(human.get("frequency")), as_number(human.get("modulation"))
    if freq is None or mod is None:
        fail(f"{where}: no frequency/modulation: {human!r}")
    out: dict[str, Any] = {
        "frequencyMHz": freq,
        "modulation": int(mod),
        "modulationName": _Modulations(constants).name(mod, where),
    }
    for key, field in (("minMHz", "minFrequency"), ("maxMHz", "maxFrequency")):
        if (n := as_number(human.get(field))) is not None:
            out[key] = n
    if isinstance(human.get("editable"), bool):
        out["editable"] = human["editable"]
    return out


def build_radios(
    units_by_type: dict[str, dict[str, Any]],
    flyable: set[str],
    constants: Constants,
    overlays: Overlays,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """Return (radios keyed by id, ``flyable`` aircraft type -> [radio ids])."""
    mods = _Modulations(constants)
    band_rules = overlays.table("radios", "bandRules")
    guard_mhz = overlays.table("radios", "guardMHz")
    step_khz = overlays.table("radios", "stepKHz")
    used_rules: set[int] = set()
    bands: set[str] = set()
    radios: dict[str, dict[str, Any]] = {}
    by_aircraft: dict[str, list[str]] = {}
    for atype in sorted(units_by_type):
        if atype not in flyable:
            continue
        ids = []
        for index, name, segments, presets in _radios_of(
            atype, units_by_type[atype], mods
        ):
            rid = f"{atype}__radio{index}"
            lo = min(s["minMHz"] for s in segments)
            hi = max(s["maxMHz"] for s in segments)
            source: dict[str, str] = {}
            band = named_band(name)
            if band is None:
                where = "overlays radios/bandRules"
                i = rule(band_rules, {"minMHz": lo, "maxMHz": hi}, where)
                if i is None:
                    fail(f"{where}: no rule matches {lo}-{hi} MHz ({rid})")
                used_rules.add(i)
                band = band_rules[i]["band"]
                source["band"] = HAND_AUTHORED
            if band not in guard_mhz:
                fail(f"overlays radios/guardMHz: no entry for band {band!r} ({rid})")
            bands.add(band)
            modulations = sorted(
                {(s["modulation"], s["modulationName"]) for s in segments}
            )
            record: dict[str, Any] = {"id": rid}
            if name is not None:
                record["name"] = name
            record |= {
                "band": band,
                "range": {"minMHz": lo, "maxMHz": hi},
                "segments": segments,
                "presets": presets,
                "guard": any(
                    s["minMHz"] <= g <= s["maxMHz"]
                    for s in segments
                    for g in guard_mhz[band]
                ),
                "modulation": [n for n, _ in modulations],
                "modulationName": [m for _, m in modulations],
            }
            source["guard"] = HAND_AUTHORED
            if band in step_khz:
                record["stepKHz"] = step_khz[band]
                source["stepKHz"] = HAND_AUTHORED
            record["_source"] = source
            radios[rid] = record
            ids.append(rid)
        if ids:
            by_aircraft[atype] = ids
    unused_rules(band_rules, used_rules, "overlays radios/bandRules")
    unused_keys(guard_mhz, bands, "overlays radios/guardMHz")
    unused_keys(step_khz, bands, "overlays radios/stepKHz")
    return radios, by_aircraft
