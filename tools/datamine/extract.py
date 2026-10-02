"""Extract per-entity reference data from a DCS ``_G`` dump.

Writes ``<out>/latest/<series>/<id>.json`` (airbases:
``airbases/<theatre>/<name>.json``; beacons:
``beacons/<theatre>/<typeName>/<beaconId>.json``; ``common.series_files``) plus
a ``manifest.json`` (``Entity.Provenance``), replacing the previous version's
data (older versions are in git history; an older DCS than ``latest`` fails).
Output is deterministic: sorted keys, stable formatting, and ``extractedAt``
taken from the version marker's mtime. Extracting into
``dcs-world-reference`` also regenerates the DCS-constant
enum types and ``country.id``/``country.name``
(``dcs_constants.generated_schemas``). The DCS install supplies the flyable
declarations (``extract_flyables``), the RWR symbol and HARM code tables
(``rwr``), the NATO speech names of air defence units (``extract_threats``),
the stock liveries and the theatres, beacons, navaids and airbases
(``extract_theatres``) and the Mission Editor's AI actions and options
(``extract_actions``, joined with this version's actions probe, else the
previous ``latest``'s marked ``probedOn``, ``actions_probe``). The per-terrain runtime dumps
(``.datamine/terrains``) add airbase names, reference points, runways and
stands and the projections of terrains without beacons (``extract_runtime``).
The cached API dump (``.datamine/api``, ``api_dump``) adds ``api/``. The
dump must be in the hook's format (``common.DUMP_FORMAT``).

    uv run python -m tools.datamine.extract [G_DIR] [--out DIR] --install-dir DIR
        [--terrains-dir DIR] [--api-dir DIR] [--probe-dir DIR] [--actions-probe-dir DIR]
        [--actions-probe-followup-dir DIR]
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import (
    action_types,
    actions_probe,
    api_dump,
    api_probe,
    api_schema,
    dcs_constants,
    dcs_database_types,
    extract_actions,
    extract_countries,
    extract_datalink,
    extract_db_tables,
    extract_flyables,
    extract_liveries,
    extract_radios,
    extract_runtime,
    extract_sensors,
    extract_stores,
    extract_theatres,
    extract_threats,
    extract_units,
    id_types,
    overlays,
    rwr,
)
from .common import (
    API_DIR,
    CACHE_DIR,
    CACHED_G_DIR,
    DUMP_FORMAT,
    MANIFEST,
    REFERENCE_DATA_DIR,
    SERIES,
    VERSION_MARKER,
    fail,
    install_version,
    json_text,
    list_lua,
    read_dump_format,
    read_version,
    series_bytes,
    to_wsl_path,
    version_data,
    warn,
    write_latest,
    write_text_if_changed,
)
from .dcs_constants import Constants
from .lua_reader import LuaReader, as_string

EXTRACTOR = "dcs-world-schema/tools/datamine@0.1.0"


@dataclass
class Extraction:
    version: str
    series: dict[str, dict[str, Any]]
    constants: Constants
    manifest: dict[str, Any]
    # The dump file texts read, by path (``LuaReader.texts``).
    texts: dict[Path, str] = field(default_factory=dict)

    def files(self) -> dict[str, bytes]:
        """The data dir: ``{relative path: bytes}``."""
        out = {MANIFEST: json_text(self.manifest).encode("utf-8")}
        for name, records in self.series.items():
            for rel, data in series_bytes(SERIES[name], records).items():
                out[f"{name}/{rel}"] = data
        return out


def _origins(*record_sets: Any) -> list[str]:
    """Distinct ``_origin`` values (the DCS plugin that registered a record)."""
    out: set[str] = set()
    for records in record_sets:
        for rec in records:
            if isinstance(rec, dict) and (origin := as_string(rec.get("_origin"))):
                out.add(origin)
    return sorted(out)


def extract(
    g_dir: Path,
    install_dir: Path,
    terrains_dir: Path | None = None,
    actions_probe_doc: dict[str, Any] | None = None,
    actions: tuple[dict[str, Any], list[str]] | None = None,
) -> Extraction:
    """Extract ``g_dir`` (and the runtime dumps in ``terrains_dir``); nothing
    is written (``Extraction.files``). ``actions_probe_doc``: this version's
    actions probe, joined into the ``actions`` records; ``actions``: the
    ``extract_actions.build`` of this install and dump, when already made."""
    version = read_version(g_dir)
    if version is None:
        fail(f"no {VERSION_MARKER} in {g_dir}")
    if (fmt := read_dump_format(g_dir)) != DUMP_FORMAT:
        fail(
            f"{g_dir} is dump format {fmt}, the extractors read {DUMP_FORMAT}; "
            "re-dump with task datamine"
        )
    install_ver = install_version(install_dir)
    if install_ver != version:
        warn(
            f"install {install_dir} is DCS {install_ver}, the dump is {version}: "
            "flyables, RWR tables and liveries come from the install"
        )
    facts = overlays.load(version)
    texts: dict[Path, str] = {}
    reader = LuaReader(g_dir, texts=texts)

    formations = extract_db_tables.read_formations(reader, g_dir)
    raw_countries = extract_countries.load_countries(reader, g_dir)
    constants = dcs_constants.load_constants(reader, g_dir)
    constants.values.update(extract_theatres.install_constants(install_dir))
    ws_ids = rwr.load_wstype_ids(reader, g_dir)

    raw = extract_units.load_units(reader, g_dir)
    extract_units.check_gun_mixes(
        raw, facts.table("aircraft", extract_units.MIX_GAPS_TABLE)
    )
    planes_helos = raw.category(*extract_units.AIRCRAFT_DIRS)
    declared = extract_flyables.declared_flyables(install_dir)
    extract_flyables.check_coverage(declared, planes_helos)
    flyable = extract_flyables.flyable_types(planes_helos, declared)
    print(
        f"Flyable aircraft: {len(flyable)} ({len(declared)} declared by the install, "
        f"{sum(1 for t in flyable if t not in declared)} only by _file_flyable)"
    )

    # Stores before aircraft: station.wet needs the fuel-tank CLSIDs.
    index = extract_stores.collect_projectiles(reader, g_dir)
    weapons, warheads = extract_stores.build_weapons_and_warheads(index, constants)
    cluster_warheads = extract_stores.add_weapon_details(weapons, warheads, index)
    launchers = reader.read_many(list_lua(g_dir / "launcher"))
    gunpods = extract_stores.load_gunpods(
        reader.read_many(list_lua(g_dir / "weapons_table" / "aircraft_gunpods"))
    )
    pod_sensors = extract_stores.load_pod_sensors(
        reader.read_many(list_lua(g_dir / "db" / "Pods" / "Pod"))
    )
    stores, racks, store_stats = extract_stores.build_stores_and_racks(
        launchers, index, constants, ws_ids, gunpods, pod_sensors
    )
    extract_stores.categories_from_launchers(weapons, launchers, constants)
    no_category = extract_stores.categories_from_bombs_table(weapons, index, constants)
    extract_stores.name_seeker_types(weapons, facts)
    fuel_clsids = {c for c, s in stores.items() if s["kind"] == "fuel-tank"}

    radios, radios_by_ac = extract_radios.build_radios(
        planes_helos, flyable, constants, facts
    )
    datalinks = extract_datalink.build_datalinks(planes_helos, flyable, install_dir)
    aircraft = extract_units.build_aircraft(
        raw, flyable, radios_by_ac, datalinks, fuel_clsids
    )
    surface = extract_units.build_surface(
        raw, set(weapons), index.by_resource, constants
    )
    print(extract_units.weapon_system_summary(surface))
    extract_units.name_reporting(surface, facts)

    countries = extract_countries.build_countries(raw_countries, constants)
    operators = extract_countries.build_operators(
        reader, g_dir, raw_countries, constants
    )
    for uid, rec in aircraft.items():
        rec["operators"] = operators.get(uid, [])
        radio = extract_radios.default_radio(uid, planes_helos[uid], constants)
        if radio is None:
            warn(f"aircraft {uid} has no HumanRadio: no defaultRadio")
        else:
            rec["defaultRadio"] = radio
    for series_key in ("ground_vehicles", "personnel", "ships"):
        for uid, rec in surface[series_key].items():
            if uid in operators:
                rec["operators"] = operators[uid]

    sensors, unknown_sensors = extract_sensors.build_sensors(
        reader,
        g_dir,
        constants,
        extract_sensors.sensor_keys(install_dir),
        pod_sensors,
    )
    all_units = raw.category(*raw.by_category)
    rwr_entries, install_ws_types = rwr.read_tables(install_dir)
    rwr.check_ws_type_constants(install_ws_types, constants.values["wsType"])
    rwr_join = rwr.join(rwr_entries, set(all_units), set(weapons), ws_ids)
    rwr.apply_to_weapons(rwr_join, weapons)
    rockets = {
        name: found[0].raw
        for name, records in index.same_name.items()
        if (found := extract_stores.rockets_records(records))
    }
    threats = extract_threats.build_threats(
        all_units,
        extract_threats.unit_dirs(raw.by_category),
        {
            uid: rec["sensors"]
            for recs in (aircraft, *surface.values())
            for uid, rec in recs.items()
            if rec.get("sensors")
        },
        {sid: rec["kind"] for sid, rec in sensors.items()},
        {
            uid: rec.get("weaponSystems", [])
            for recs in surface.values()
            for uid, rec in recs.items()
        },
        weapons,
        rockets,
        rwr_join,
        extract_threats.nato_names(install_dir),
        facts,
    )
    print(
        f"RWR table entries joined: {dict(sorted(rwr_join.joined.items()))}; "
        f"weapons with an RWR symbol/code: "
        f"{dict(sorted(rwr_join.projectiles.items()))}"
    )
    print(extract_threats.summary(threats))
    for line in rwr.ammunition_report(ws_ids):
        print(f"Unit ammunition without an exact projectile: {line}")

    # Gun pods' shells are Entity.GunAmmo too.
    raw.gun_ammo.update(a for s in stores.values() for a in s.get("gunAmmo", []))
    series: dict[str, dict[str, Any]] = {
        "aircraft": aircraft,
        **surface,
        "sensors": sensors,
        "radios": radios,
        "datalink": datalinks,
        "weapons": weapons,
        "warheads": warheads,
        "stores": stores,
        "racks": racks,
        "gun_ammo": extract_units.build_gun_ammo(raw, reader, g_dir),
        "attributes": extract_units.build_attributes(raw),
        "countries": countries,
        "threats": threats,
        **extract_db_tables.build(
            reader, g_dir, formations, raw_countries, all_units, constants
        ),
    }
    series["liveries"], problems = extract_liveries.build_liveries(
        install_dir,
        list(countries.values()),
        all_units,
        facts.table("liveries", extract_liveries.GAPS_TABLE),
    )
    geo, fit_report = extract_theatres.build(install_dir, constants, facts)
    dumps = extract_runtime.load(terrains_dir, version)
    fit_report += extract_theatres.runtime_projections(geo["theatres"], dumps)
    runtime_report = extract_runtime.merge(geo, dumps)
    series.update(geo)
    action_series, action_report = actions or extract_actions.build(
        install_dir, g_dir, reader, formations=formations
    )
    if actions_probe_doc is not None:
        action_report = [
            *action_report,
            *(
                f"problem: {p}"
                for p in actions_probe.join(actions_probe_doc, action_series["actions"])
            ),
        ]
    series.update(action_series)
    overlays.apply(facts, series)
    extract_units.index_attribute_units(series)

    stats = reader.stats
    for c in constants.manifest():
        print(f"DCS constants {c['family']}: {c['count']}")
    for line in fit_report:
        print(f"Projection {line}")
    for line in runtime_report:
        print(f"Runtime {line}")
    for line in action_report:
        if line.startswith("problem: "):
            problems.append(f"actions: {line.removeprefix('problem: ')}")
        else:
            print(line)
    print(f"Runtime dumps: {', '.join(sorted(dumps)) or '(none)'}")
    print(f"Store -> weapon join basis: {dict(sorted(store_stats.basis.items()))}")
    for clsid, (shaped, weapon) in sorted(store_stats.loader_overrides.items()):
        print(f"Store {clsid}: loaders name {weapon}, not its shape match {shaped}")
    for clsid, names in sorted(store_stats.loader_conflicts.items()):
        print(f"Store {clsid}: loaders name different weapons {names}; kept its shapes")
    for clsid, names in sorted(store_stats.ids_ambiguous.items()):
        print(
            f"Store {clsid}: raw attribute tuple is the ws_type of {names}; kept its shapes"
        )
    print(
        f"Stores delivering no weapon or gun ammo, by kind: {dict(sorted(store_stats.no_delivers.items()))}"
    )
    print(
        f"Weapons whose warhead is their cluster's: {len(cluster_warheads)}; "
        f"aircraft gunpods no store takes: {store_stats.unused_gunpods}; "
        f"db.Pods no store takes: {store_stats.unused_pods}"
    )
    problems += [
        *(f"parse failure: {p}: {e}" for p, e in stats.failures),
        *(f"unresolved ref in {p}: {r}" for p, r in stats.unresolved_refs),
        *(f"store kind unknown: {c}" for c in store_stats.unknown_kind),
        *(
            f"store slot-4 weapon {n!r} is not a projectile: {k} store(s)"
            for n, k in sorted(store_stats.unknown_weapon.items())
        ),
        *(f"sensor kind unknown: {n}" for n in unknown_sensors),
        *(f"RWR table key joins nothing: {k}" for k in rwr_join.unmatched),
        *(f"RWR table key DCS cannot match: {k}" for k in rwr_join.unkeyed),
        *(
            f"unresolved {t} value {v!r}: {n} occurrence(s)"
            for (t, v), n in sorted(constants.unresolved.items(), key=str)
        ),
    ]
    if no_category:
        problems.append(
            f"{len(no_category)} weapon(s) without category (no wsType level 2 of "
            "their own, from agreeing exact-delivering launchers or from _G/bombs): "
            + ", ".join(no_category)
        )
    for line in problems:
        warn(line)
    if stats.failures or stats.unresolved_refs:
        fail(
            f"{len(stats.failures)} parse failure(s), {len(stats.unresolved_refs)} unresolved ref(s)"
        )

    mtime = (g_dir / VERSION_MARKER).stat().st_mtime
    manifest = {
        "dcsVersion": version,
        "extractedAt": dt.datetime.fromtimestamp(mtime, tz=dt.UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "extractor": EXTRACTOR,
        "source": "_G self-dump",
        "constants": constants.manifest(),
        "modulesPresent": _origins(
            (rec for bucket in raw.by_category.values() for rec in bucket.values()),
            (proj.raw for proj in index.by_name.values()),
            (rec for _, rec in launchers),
        ),
    }
    for name in SERIES:
        if name in series:
            print(f"  {name:16s} {len(series[name]):5d}")
    return Extraction(version, series, constants, manifest, texts)


def api_version_files(
    version: str,
    install: Path | None,
    data_root: Path,
    api_dir: Path = api_dump.CACHED_API_DIR,
    probe_dir: Path = api_probe.CACHED_PROBE_DIR,
    probes: Sequence[actions_probe.Probe] = (
        actions_probe.MAIN,
        actions_probe.FOLLOWUP,
    ),
) -> dict[str, bytes]:
    """Every ``api/`` file of DCS ``version`` under ``data_root``: the API
    dump's, the argument probe's and each actions probe's (``probes``), cached
    for this version, else kept from ``latest`` (probes carried forward from
    an older ``latest``)."""
    files = {
        **api_dump.version_files(
            api_dir, version, install, version_data(data_root, version)
        ),
        **replace(api_probe.CACHE, dir=probe_dir).version_files(version, data_root),
    }
    for probe in probes:
        files.update(probe.store.version_files(version, data_root))
    return files


def write_generated_schema(constants: Constants) -> None:
    for path, text in dcs_constants.generated_schemas(constants).items():
        if write_text_if_changed(path, text):
            print(f"Regenerated {path}")


def publish_latest(ver_dir: Path, extraction: Extraction, g_dir: Path) -> None:
    """Regenerate the schema types of the reference data in ``ver_dir``
    (``extraction`` of ``g_dir``): the DCS constant enums, the AI action
    types (``action_types``), the id types (``id_types``), the DCS database table types
    (``dcs_database_types``) and the hooks/server/export env globals
    (``api_schema``, from its ``api/``)."""
    write_generated_schema(extraction.constants)
    action_types.write(action_types.generate_from(ver_dir))
    id_types.write(id_types.generate(ver_dir))
    dcs_database_types.write(
        dcs_database_types.generate(g_dir, texts=extraction.texts),
        dcs_database_types.OUT_DIR,
    )
    api_schema.write(api_schema.generate(ver_dir / API_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract DCS reference data from a _G dump."
    )
    parser.add_argument(
        "g_dir",
        type=Path,
        nargs="?",
        default=CACHED_G_DIR,
        help="_G dump dir (default: .datamine/_G).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REFERENCE_DATA_DIR,
        help="Output root (default: dcs-world-reference).",
    )
    parser.add_argument(
        "--install-dir",
        default=os.environ.get("DCS_INSTALL_DIR"),
        help="DCS install, for flyable declarations, RWR tables, builtin liveries and terrains (default: DCS_INSTALL_DIR).",
    )
    parser.add_argument(
        "--terrains-dir",
        type=Path,
        default=CACHE_DIR / "terrains",
        help="Per-terrain runtime dumps (default: .datamine/terrains; absent = none).",
    )
    parser.add_argument(
        "--api-dir",
        type=Path,
        default=api_dump.CACHED_API_DIR,
        help="Cached API dump (default: .datamine/api); when it is not of this "
        "version latest's api/ files are kept.",
    )
    parser.add_argument(
        "--probe-dir",
        type=Path,
        default=api_probe.CACHED_PROBE_DIR,
        help="Cached argument probe (default: .datamine/probe); when it is not "
        "of this version latest's api/probe.json is kept (carried forward, "
        "probedOn, when latest is an older version).",
    )
    parser.add_argument(
        "--actions-probe-dir",
        type=Path,
        default=actions_probe.MAIN.cache,
        help="Cached actions probe (default: .datamine/actions-probe); when it is "
        "not of this version latest's api/actions-probe.json is kept (carried "
        "forward, probedOn, when latest is an older version).",
    )
    parser.add_argument(
        "--actions-probe-followup-dir",
        type=Path,
        default=actions_probe.FOLLOWUP.cache,
        help="Cached actions probe follow-up (default: "
        ".datamine/actions-probe-followup), as --actions-probe-dir for "
        "api/actions-probe-followup.json.",
    )
    args = parser.parse_args()
    if not args.g_dir.is_dir():
        parser.error(f"_G dir not found: {args.g_dir}")
    if not args.install_dir:
        parser.error("--install-dir (or DCS_INSTALL_DIR) is required")
    install = to_wsl_path(args.install_dir)
    g_version = read_version(args.g_dir)
    main_probe = replace(actions_probe.MAIN, cache=args.actions_probe_dir)
    probe_doc = main_probe.load(g_version, args.out) if g_version else None
    result = extract(args.g_dir, install, args.terrains_dir, probe_doc)
    files = {
        **result.files(),
        **api_version_files(
            result.version,
            install,
            args.out,
            args.api_dir,
            args.probe_dir,
            (
                main_probe,
                replace(actions_probe.FOLLOWUP, cache=args.actions_probe_followup_dir),
            ),
        ),
    }
    latest = write_latest(args.out, files)
    print(f"DCS {result.version}: written to {latest}")
    if args.out.resolve() == REFERENCE_DATA_DIR.resolve():
        publish_latest(latest, result, args.g_dir)
    else:
        print("Not dcs-world-reference: generated types left as is")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
