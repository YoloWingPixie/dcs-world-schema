"""The lookup helpers against brute-force scans of the bundles: every ``x-ref``
the entity JSON Schema declares is found by walking each record's values with
the schema, independently of the index builder."""

from __future__ import annotations

import json
import typing
from collections import defaultdict
from collections.abc import Iterator, Mapping
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, get_args

import dcs_world_reference as ref
import pytest

SCHEMA = Path(__file__).resolve().parents[3] / "dist" / "dcs-world-entities.schema.json"
ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
Refs = dict[str, dict[str, set[tuple[str, str, str]]]]


def _bundle(name: str) -> Mapping[str, Any]:
    return typing.cast(Mapping[str, Any], getattr(ref, name)())


def _type_series() -> dict[str, str]:
    """``Entity.<Type>`` -> series, from the loaders' return types."""
    out: dict[str, str] = {}
    for name in ref.SERIES:
        record = get_args(typing.get_type_hints(getattr(ref, name))["return"])[1]
        out[f"Entity.{record.__name__}"] = name
    return out


def _refs_in(
    defs: dict[str, Any], node: Any, value: Any, path: str
) -> Iterator[tuple[str, list[str], str]]:
    """(path, x-ref types, value) of every reference ``value`` holds."""
    if not isinstance(node, dict):
        return
    if "x-ref" in node and isinstance(value, str | int) and not isinstance(value, bool):
        yield path, node["x-ref"], str(value)
    if "$ref" in node:
        target = defs[node["$ref"].rsplit("/", 1)[-1]]
        yield from _refs_in(defs, target, value, path)
    for sub in node.get("anyOf", []):
        yield from _refs_in(defs, sub, value, path)
    if "items" in node and isinstance(value, list):
        for item in value:
            yield from _refs_in(defs, node["items"], item, f"{path}[]")
    if isinstance(value, dict):
        for key, sub in node.get("properties", {}).items():
            if key in value:
                yield from _refs_in(
                    defs, sub, value[key], f"{path}.{key}" if path else key
                )


@cache
def _scan() -> tuple[Refs, frozenset[tuple[str, str]]]:
    """{target series: {id: {(series, id, path)}}} and the (series, path)
    pairs seen, by scanning every record."""
    if not SCHEMA.is_file():
        pytest.skip(f"{SCHEMA} missing (run `task package`)")
    defs = json.loads(SCHEMA.read_text(encoding="utf-8"))["definitions"]
    by_type = _type_series()
    found: Refs = defaultdict(lambda: defaultdict(set))
    relations: set[tuple[str, str]] = set()
    for series in ref.SERIES:
        type_name = next(t for t, s in by_type.items() if s == series)
        for key, record in _bundle(series).items():
            for path, types, value in _refs_in(defs, defs[type_name], record, ""):
                relations.add((series, path))
                for target in {by_type[t] for t in types}:
                    if value in _bundle(target):
                        found[target][value].add((series, key, path))
    return found, frozenset(relations)


@pytest.mark.parametrize("series", ref.SERIES)
def test_references_to_matches_scan(series: ref.SeriesName) -> None:
    found, _ = _scan()
    for key in _bundle(series):
        got = {
            (r["series"], r["id"], r["path"]) for r in ref.references_to(series, key)
        }
        assert got == found.get(series, {}).get(key, set()), (series, key)
    assert ref.references_to(series, "\x00no such id") == []


def test_every_relation_is_declared() -> None:
    _, relations = _scan()
    meta = json.loads(
        files("dcs_world_reference")
        .joinpath("data", "_index", "meta.json")
        .read_text("utf-8")
    )
    declared = {(r["series"], r["path"]) for r in meta["relations"]}
    assert relations <= declared
    assert relations  # the scan found references


def _delivering(weapon: str) -> set[str]:
    return {
        k
        for k, s in ref.stores().items()
        if any(d.get("weapon") == weapon for d in s.get("delivers", []))
    }


def test_stores_and_aircraft_for_every_weapon() -> None:
    accepts = {
        k: {c["clsid"] for st in a.get("stations", []) for c in st.get("accepts", [])}
        for k, a in ref.aircraft().items()
    }
    for weapon in ref.weapons():
        stores = _delivering(weapon)
        assert ref.stores_delivering(weapon) == sorted(stores), weapon
        carriers = sorted(k for k, acc in accepts.items() if acc & stores)
        assert ref.aircraft_carrying(weapon) == carriers, weapon
    assert "F-16C_50" in ref.aircraft_carrying("AIM_120C")
    # B-52H has AGM-84A only on an obsolete launcher
    assert "B-52H" not in ref.aircraft_carrying("AGM_84A")
    assert ref.aircraft_carrying("no such weapon") == []


def test_threats_for_every_unit() -> None:
    expected: dict[str, set[str]] = defaultdict(set)
    for key, threat in ref.threats().items():
        units = [threat.get("unit")] + [
            c.get("unit") for c in threat.get("components", [])
        ]
        for unit in units:
            if unit is not None:
                expected[unit].add(key)
    for series in ("aircraft", "ground_vehicles", "personnel", "ships", "structures"):
        for unit in _bundle(series):
            assert ref.threats_for_unit(unit) == sorted(expected.get(unit, set())), unit


@pytest.mark.parametrize("series", ref.SERIES)
def test_find_by_name(series: ref.SeriesName) -> None:
    by_key: dict[str, set[str]] = defaultdict(set)
    for key, record in _bundle(series).items():
        for field in ("displayName", "name"):
            value = record.get(field)
            if isinstance(value, str) and ref.name_key(value):
                by_key[ref.name_key(value)].add(key)
    for name, ids in by_key.items():
        assert ref.find_by_name(series, name) == sorted(ids)
        assert ref.find_by_name(series, f" {name.translate(ASCII_UPPER)} ") == sorted(
            ids
        )
    assert ref.find_by_name(series, "\x00no such name") == []


def test_airbase_by_name() -> None:
    for key, airbase in ref.airbases().items():
        name, theatre = airbase["name"], airbase["theatre"]
        assert key in ref.airbase_by_name(name, theatre)
        assert key in ref.airbase_by_name(name.lower(), theatre.translate(ASCII_UPPER))
        assert key in ref.airbase_by_name(f" {name.translate(ASCII_UPPER)}")
    assert ref.airbase_by_name("Batumi", "Caucasus") == ["Caucasus.22"]
    assert ref.airbase_by_name("Batumi", "Syria") == []


def test_indexes_are_canonical_json() -> None:
    index_dir = files("dcs_world_reference").joinpath("data", "_index")
    names = [p.name for p in index_dir.iterdir()]
    assert "meta.json" in names and "carriers.json" in names
    for name in names:
        text = index_dir.joinpath(name).read_text("utf-8")
        canonical = json.dumps(
            json.loads(text), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        assert text == canonical + "\n", name


def test_typed_helpers() -> None:
    refs: list[ref.Reference] = ref.references_to("weapons", "AIM_120C")
    series: ref.SeriesName = refs[0]["series"]
    stores: list[str] = ref.stores_delivering("AIM_120C")
    assert series in ref.SERIES and stores
    assert all(r["path"] for r in refs)
