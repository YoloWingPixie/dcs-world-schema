"""Extract ``Entity.Livery`` records.

Liveries are not in the ``_G`` dump; the stock ones are found in the install:

* ``<install>/CoreMods/<kind>/<module>/Liveries/<unitType>/<name>/``
* ``<install>/Bazar/Liveries/<unitType>/<name>/``

The ``<unitType>`` folder is a livery entry point: the Mission Editor looks up a
unit's liveries under its ``livery_entry``, else its type, with ``/`` as ``_``
(MissionEditor/modules/me_db_api.lua ``liveryEntryPoint``, loadLiveries.lua
``fixUnitType``), case-insensitively as Windows paths are. ``unitTypes`` lists
the units with that entry point.

``name`` and ``countries`` come from each folder's ``description.lua``, run in
the Lua sandbox (third-party files). The Mission Editor asks for a unit's
liveries with its country's ``ShortName`` (loadLiveries.lua ``loadSchemes``,
called with ``country.ShortName``; nil, for all countries, when there is no
country or it is the CJTF ``BLUE``/``RED``), so the strings of ``countries``
are matched exactly against the extracted countries' ``shortName``:

* no ``countries`` (or no ``description.lua``): the livery is every country's;
  the record has no ``countries``.
* a ``countries`` table: ``countries``/``countryNames`` hold the countries it
  names, as listed (``countries = {}`` names none), and ``unmappedCountries``
  the strings no country has as its ``ShortName``. Each such string must be a
  key of the overlay table ``liveries/unmappedCountryUpstreamGaps``, and every
  key of that table must be such a string, or the extraction fails.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import assign_defined, fail, pmap, read_text
from .lua_reader import lua_table_type, sandbox_exec
from .overlays import unused_keys

DESCRIPTION = "description.lua"
GAPS_TABLE = "unmappedCountryUpstreamGaps"


@dataclass
class LiveryWalk:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    failures: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class _Folder:
    unit_type: str
    folder: Path
    module: str | None


def _subdirs(directory: Path) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(directory) as it:
            return sorted((e for e in it if e.is_dir()), key=lambda e: e.name)
    except FileNotFoundError:
        return []


def _folders(liveries_dir: Path, module: str | None) -> list[_Folder]:
    """One entry per ``<unitType>/<name>`` folder; nothing deeper is visited."""
    units = _subdirs(liveries_dir)
    return [
        _Folder(unit.name, Path(name.path), module)
        for unit, names in zip(
            units, pmap(lambda u: _subdirs(Path(u.path)), units), strict=True
        )
        for name in names
    ]


def _description(folder: _Folder) -> str | None:
    """The folder's ``description.lua`` text; None when it has none."""
    try:
        return read_text(folder.folder / DESCRIPTION)
    except (FileNotFoundError, IsADirectoryError):
        return None


def _parse_description(
    text: str, name: str
) -> tuple[dict[str, Any] | None, str | None]:
    ok, env = sandbox_exec(text, name)
    if not ok:
        return None, str(env)
    out: dict[str, Any] = {}
    title = env["name"]
    if isinstance(title, str) and title.strip():
        out["name"] = title.strip()
    countries = env["countries"]
    if countries is None:
        return out, None
    if not isinstance(countries, lua_table_type()):
        fail(f"{name}: countries is a {type(countries).__name__}, not a table")
    values = list(countries.values())
    if not all(isinstance(v, str) for v in values):
        fail(f"{name}: countries holds a non-string entry: {values!r}")
    out["countries"] = sorted(set(values))
    return out, None


def walk_liveries(install_dir: Path) -> LiveryWalk:
    """Every livery under the install, keyed by its ``id`` (its ``path``)."""
    folders: list[_Folder] = []
    coremods = install_dir / "CoreMods"
    for liveries in sorted(coremods.glob("*/*/Liveries"), key=lambda p: p.as_posix()):
        module = liveries.parent.relative_to(coremods).as_posix()
        folders += _folders(liveries, module)
    folders += _folders(install_dir / "Bazar" / "Liveries", None)

    walk = LiveryWalk()
    for f, text in zip(folders, pmap(_description, folders), strict=True):
        parsed: dict[str, Any] = {}
        desc = f.folder / DESCRIPTION
        if text is not None:
            result, error = _parse_description(text, str(desc))
            if result is None:
                walk.failures.append((str(desc), error or ""))
            else:
                parsed = result
        path = (desc if text is not None else f.folder).relative_to(install_dir)
        record: dict[str, Any] = {
            "id": path.as_posix(),
            "entryPoint": f.unit_type,
            "name": parsed.get("name") or f.folder.name,
            "path": path.as_posix(),
        }
        if "countries" in parsed:
            record["countries"] = parsed["countries"]
        assign_defined(record, {"module": f.module})
        walk.records[record["id"]] = record
    return walk


def map_countries(
    records: dict[str, dict[str, Any]], countries: list[dict[str, Any]]
) -> dict[str, set[str]]:
    """Replace the ``countries`` short names of the records that list any with
    ``country.id`` values in place, with their constant names (the country
    record's ``idName``) in ``countryNames`` and the strings no country has as
    its ``shortName`` in ``unmappedCountries``. Returns unmapped string ->
    livery ids."""
    by_short: dict[str, tuple[int, str]] = {}
    for c in countries:
        if "shortName" not in c:
            continue
        if "idName" not in c:
            fail(f"country {c['id']} ({c['shortName']}) has no idName")
        if c["shortName"] in by_short:
            fail(
                f"countries {by_short[c['shortName']][0]} and {c['id']} share shortName {c['shortName']!r}"
            )
        by_short[c["shortName"]] = (c["id"], c["idName"])
    unmapped: dict[str, set[str]] = {}
    for key, record in records.items():
        if "countries" not in record:
            continue
        pairs = sorted({by_short[s] for s in record["countries"] if s in by_short})
        missing = sorted(s for s in record["countries"] if s not in by_short)
        for short in missing:
            unmapped.setdefault(short, set()).add(key)
        record["countries"] = [i for i, _ in pairs]
        record["countryNames"] = [n for _, n in pairs]
        if missing:
            record["unmappedCountries"] = missing
    return unmapped


def entry_points(units: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Lowercased livery entry point -> the unit types using it."""
    out: dict[str, list[str]] = {}
    for uid, rec in sorted(units.items()):
        entry = rec.get("livery_entry")
        entry = entry if isinstance(entry, str) else uid
        out.setdefault(entry.replace("/", "_").lower(), []).append(uid)
    return out


def check_unmapped(unmapped: dict[str, set[str]], gaps: dict[str, str]) -> None:
    """Fail on an unmapped country string ``gaps`` does not explain, and on a
    ``gaps`` key that is not unmapped."""
    where = f"overlays liveries/{GAPS_TABLE}"
    unknown = sorted(set(unmapped) - set(gaps))
    if unknown:
        fail(
            "livery countries no country has as its shortName: "
            + "; ".join(
                f"{s!r} ({len(unmapped[s])} livery record(s), e.g. {min(unmapped[s])})"
                for s in unknown
            )
            + f"; fix the mapping or explain them in {where}"
        )
    unused_keys(gaps, set(unmapped), where)


def build_liveries(
    install_dir: Path,
    countries: list[dict[str, Any]],
    units: dict[str, dict[str, Any]],
    gaps: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """(livery records keyed by id, problems to warn about). ``gaps`` is the
    ``unmappedCountryUpstreamGaps`` overlay table."""
    walk = walk_liveries(install_dir)
    check_unmapped(map_countries(walk.records, countries), gaps)
    by_entry = entry_points(units)
    for record in walk.records.values():
        record["unitTypes"] = by_entry.get(record["entryPoint"].lower(), [])
    no_unit = sorted(
        {r["entryPoint"] for r in walk.records.values() if not r["unitTypes"]}
    )
    problems = [
        f"description.lua failed ({error}): {path}" for path, error in walk.failures
    ]
    if no_unit:
        problems.append(
            f"{len(no_unit)} livery entry point(s) match no unit type: {', '.join(no_unit)}"
        )
    return walk.records, problems
