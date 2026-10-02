"""Hand tables the package helpers apply, from ``tools/datamine/overlays.yaml``,
checked against the data and shipped as indexes:

* ``tacan`` (``beacons/tacanPlan``): the DME/TACAN channel plan of
  ``tacanFrequency``, ``tacanChannel`` and ``isValidTacan``. Every beacon of
  its ``beaconTypes`` with a ``channel`` of 1 or more (DCS writes 0 for none)
  must have that channel in the plan and, with a ``frequencyHz``, a frequency
  equal to the channel's reply or paired VHF frequency in either band, unless
  ``beacons/tacanPlanExceptions`` lists it; an exception that now matches or
  names no beacon is stale.
* ``countryAliases`` (``countries/aliases``): ``name_key(alias)`` -> country
  id for ``countryId``. The countries' own names (name, shortName,
  internationalName, idName, oldId) must be unambiguous; an alias equal to
  one of them, shared by two countries, or for an unknown idName fails.
* ``allLiveryCountries`` (``countries/allLiveries``): country id (a string)
  -> ``shortName`` of each country whose shortName the table lists, offered
  every livery by ``liveriesFor``; a shortName no country or two countries
  have fails.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from tools.datamine import overlays
from tools.datamine.common import fail

from .indexes import name_key

COUNTRY_NAME_FIELDS = ("name", "shortName", "internationalName", "idName", "oldId")


def _range(entry: Any, where: str) -> tuple[int, int]:
    if (
        not isinstance(entry, dict)
        or not isinstance(entry.get("from"), int)
        or not isinstance(entry.get("to"), int)
        or entry["from"] > entry["to"]
    ):
        fail(f"{where}: needs integer `from` <= `to`")
    return entry["from"], entry["to"]


def _in(ranges: list[dict[str, Any]], channel: int) -> dict[str, Any] | None:
    return next((r for r in ranges if r["from"] <= channel <= r["to"]), None)


def reply_mhz(plan: Mapping[str, Any], channel: int, band: str) -> int:
    """Ground reply (transponder transmit) frequency, MHz."""
    base = plan["interrogationMHz"]["base"] + channel - plan["channels"]["first"]
    hit = _in(plan["replyOffsetMHz"][band], channel)
    assert hit is not None
    return int(base + hit["offset"])


def vhf_khz(plan: Mapping[str, Any], channel: int, band: str) -> int | None:
    """Paired VOR/ILS frequency, kHz, or None for an unpaired channel."""
    pairing = plan["vhfPairing"]
    hit = _in(pairing["ranges"], channel)
    if hit is None:
        return None
    return int(
        hit["baseKHz"]
        + (channel - hit["from"]) * pairing["stepKHz"]
        + pairing["bandOffsetKHz"][band]
    )


def check_plan(plan: Any) -> dict[str, Any]:
    where = "overlays beacons/tacanPlan"
    if not isinstance(plan, dict):
        fail(f"{where}: needs a mapping")
    first, last = _range(
        {
            "from": plan.get("channels", {}).get("first"),
            "to": plan.get("channels", {}).get("last"),
        },
        f"{where} channels",
    )
    bands = plan.get("bands")
    if (
        not isinstance(bands, list)
        or not bands
        or not all(isinstance(b, str) for b in bands)
    ):
        fail(f"{where}: needs `bands`, a list of strings")
    if not isinstance(plan.get("interrogationMHz", {}).get("base"), int):
        fail(f"{where}: needs integer `interrogationMHz.base`")
    for band in bands:
        ranges = plan.get("replyOffsetMHz", {}).get(band)
        if not isinstance(ranges, list):
            fail(f"{where}: no replyOffsetMHz for band {band}")
        for r in ranges:
            _range(r, f"{where} replyOffsetMHz.{band}")
            if not isinstance(r.get("offset"), int):
                fail(f"{where} replyOffsetMHz.{band}: needs integer `offset`")
        for ch in range(first, last + 1):
            if sum(1 for r in ranges if r["from"] <= ch <= r["to"]) != 1:
                fail(f"{where}: channel {ch}{band} needs exactly one reply offset")
    pairing = plan.get("vhfPairing")
    if not isinstance(pairing, dict) or not isinstance(pairing.get("stepKHz"), int):
        fail(f"{where}: needs `vhfPairing` with integer `stepKHz`")
    for r in pairing.get("ranges", []):
        lo, hi = _range(r, f"{where} vhfPairing")
        if lo < first or hi > last or not isinstance(r.get("baseKHz"), int):
            fail(
                f"{where} vhfPairing: range {lo}-{hi} needs integer baseKHz within the channels"
            )
    if set(pairing.get("bandOffsetKHz", {})) != set(bands):
        fail(f"{where}: vhfPairing.bandOffsetKHz needs one offset per band")
    types = plan.get("beaconTypes")
    if not isinstance(types, list) or not types:
        fail(f"{where}: needs `beaconTypes`, a list of BEACON_TYPE names")
    return plan


def check_beacons(
    plan: Mapping[str, Any],
    exceptions: Any,
    beacons: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Report lines; fails on a beacon the plan cannot reproduce."""
    where = "overlays beacons/tacanPlan"
    if not isinstance(exceptions, dict):
        fail("overlays beacons/tacanPlanExceptions: needs a mapping")
    known_types = {b["typeName"] for b in beacons.values()}
    if unknown := sorted(set(plan["beaconTypes"]) - known_types):
        fail(f"{where}: no beacon has type {unknown}")
    first, last = plan["channels"]["first"], plan["channels"]["last"]
    counts: Counter[str] = Counter()
    bad: list[str] = []
    used: set[str] = set()
    for bid, b in sorted(beacons.items()):
        if b["typeName"] not in plan["beaconTypes"] or b.get("channel", 0) < 1:
            continue
        ch = b["channel"]
        if ch != int(ch) or not first <= ch <= last:
            bad.append(f"{bid}: channel {ch} outside {first}-{last}")
            continue
        ch = int(ch)
        if "frequencyHz" not in b:
            counts["channel only"] += 1
            continue
        khz = b["frequencyHz"] / 1000
        kinds = sorted(
            f"{kind} {band}"
            for band in plan["bands"]
            for kind, value in (
                ("reply", reply_mhz(plan, ch, band) * 1000),
                ("VHF pairing", vhf_khz(plan, ch, band)),
            )
            if value is not None and abs(value - khz) < 1e-6
        )
        if kinds:
            if bid in exceptions:
                fail(
                    f"overlays beacons/tacanPlanExceptions: {bid} now matches "
                    f"({', '.join(kinds)}); remove it"
                )
            counts[kinds[0]] += 1
        elif bid in exceptions:
            used.add(bid)
        else:
            bad.append(
                f"{bid} ({b['typeName']} channel {ch}): {b['frequencyHz'] / 1e6:g} MHz "
                "is no reply or paired VHF frequency of the channel"
            )
    if bad:
        fail(f"{where} cannot reproduce {len(bad)} beacon(s):\n  " + "\n  ".join(bad))
    overlays.unused_keys(exceptions, used, "overlays beacons/tacanPlanExceptions")
    return [
        "tacan plan: "
        + ", ".join(f"{k} {n}" for k, n in sorted(counts.items()))
        + f", listed exceptions {len(used)}"
    ]


def country_aliases(
    aliases: Any, countries: Mapping[str, Mapping[str, Any]]
) -> dict[str, int]:
    where = "overlays countries/aliases"
    owners: dict[str, int] = {}
    for c in countries.values():
        for field in COUNTRY_NAME_FIELDS:
            name = c.get(field)
            if isinstance(name, str) and name_key(name):
                other = owners.setdefault(name_key(name), c["id"])
                if other != c["id"]:
                    fail(f"countries {other} and {c['id']} are both named {name!r}")
    if not isinstance(aliases, dict):
        fail(f"{where}: needs a mapping")
    by_id_name = {c.get("idName"): c["id"] for c in countries.values()}
    out: dict[str, int] = {}
    for id_name, names in aliases.items():
        if id_name not in by_id_name:
            fail(f"{where}: no country with idName {id_name!r}")
        if not isinstance(names, list) or not names:
            fail(f"{where}: {id_name} needs a list of aliases")
        for alias in names:
            key = name_key(str(alias))
            if not key or key in owners or key in out:
                fail(
                    f"{where}: alias {alias!r} of {id_name} is empty or already names a country"
                )
            out[key] = by_id_name[id_name]
    return dict(sorted(out.items()))


def all_livery_countries(
    short_names: Any, countries: Mapping[str, Mapping[str, Any]]
) -> dict[str, str]:
    where = "overlays countries/allLiveries"
    if not isinstance(short_names, list) or not short_names:
        fail(f"{where}: needs a list of country shortNames")
    out: dict[str, str] = {}
    for short in short_names:
        hits = [c["id"] for c in countries.values() if c.get("shortName") == short]
        if len(hits) != 1:
            fail(f"{where}: {len(hits)} countries have shortName {short!r}, not one")
        out[str(hits[0])] = str(short)
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def build(
    series: Mapping[str, Mapping[str, Any]], dcs_version: str
) -> tuple[dict[str, Any], list[str]]:
    """({index name: payload}, report lines)."""
    tables = overlays.load(dcs_version)
    plan = check_plan(tables.table("beacons", "tacanPlan"))
    report = check_beacons(
        plan,
        tables.table("beacons", "tacanPlanExceptions"),
        series.get("beacons", {}),
    )
    aliases = country_aliases(
        tables.table("countries", "aliases"), series.get("countries", {})
    )
    report.append(f"country aliases: {len(aliases)}")
    every = all_livery_countries(
        tables.table("countries", "allLiveries"), series.get("countries", {})
    )
    report.append(f"all-livery countries: {len(every)}")
    return {
        "tacan": plan,
        "countryAliases": aliases,
        "allLiveryCountries": every,
    }, report
