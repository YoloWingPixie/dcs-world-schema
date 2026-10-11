"""Extract ``Entity.RwrCode`` records: one per entry of every RWR symbol and
HARM/ALIC code table the install defines, joined to unit types, weapons and
threats.

Tables (``FAMILIES``), each run in the ``rwr`` Lua sandbox:

* ``AN/ALR``: ``AN_ALR_SymbolsBase.lua`` ``symbols`` and ``symbols_strings``
  (symbols) and ``AN_ALR_HarmIDs.lua`` ``symbolID`` and ``symbols_stringsID``
  (HARM/ALIC codes), as ``rwr.read_tables`` reads them; one row per name of a
  ``symbols_stringsID`` entry;
* ``RU ELINT``: ``RU_ELINT_Symbols.lua`` ``symbols`` and ``symbols_strings``
  (both lists of ``{key, symbol, ...}``);
* ``SPO-15``: ``SPO_15_symbols.lua`` ``spo_15_symbols`` (``{type = wsType}`` or
  ``{name = unit type}`` with ``symbol``, a number of the file's local
  ``SPO_15_types``, whose letter is the value);
* ``C-130J CDMS``: the C-130J's ``CDMS/symbols.lua`` ``symbols`` and
  ``symbols_strings``, whose values are glyphs of its ``f_`` lookup table: the
  value is the ``f_`` key naming the glyph (``H+hat``);
* ``F-15E ALR-56C``: the F-15E's ``ALR56C_LIB.lua`` ``rwr_codes``
  (``[unit type] = {code, desc}``);
* ``M-2000C SERVAL``: the M-2000C's ``SERVAL.lua`` ``rwr_codes``
  (``[unit type] = {symb, desc}``; ``symb`` is a font glyph).

The common cockpit files are required; a module's file is skipped with a
warning when the module is not installed. A key joins exactly as ``rwr.join``
does (unit type or projectile name; a wsType tuple through the dump's
``__wstype_ids__.lua``); an entry joining nothing is kept, without links.
``threats`` are the threat systems whose unit or components include a joined
unit. ``id`` is ``<family slug>:<table>:<key>:<value>`` (``#n`` appended to a
repeat).

``htsClass`` (F-16C HTS threat class) is hand-authored: the overlay table
``rwr_codes/htsClass`` maps the manual's rows to unit types
(``apply_hts_classes``). It goes on each ``AN/ALR`` row whose units all have
one class, on each threat component of such a unit and on an emitter threat
(``ewr``, ``ship``, ``aircraft``) of one, stamped ``hand-authored``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lupa import lua_type

from .common import HAND_AUTHORED, fail, warn
from .rwr import (
    COCKPIT,
    HARM_IDS,
    SYMBOL_TABLES,
    SYMBOLS,
    Key,
    WsTypeIds,
    read_tables,
    resolve,
    run_install_script,
    table_key,
    table_value,
)

RU_ELINT = COCKPIT / "RU_ELINT_Symbols.lua"
SPO_15 = COCKPIT / "SPO_15_symbols.lua"
C130J = Path("Mods/aircraft/C130J/Cockpit/Scripts/CDMS/symbols.lua")
F15E = Path("Mods/aircraft/F-15E/Cockpit/Scripts/ALR56C_LIB.lua")
M2000C = Path("Mods/aircraft/M-2000C/Cockpit/Scripts/SERVAL.lua")

SYMBOL = "symbol"
ALIC = "alic"


@dataclass(frozen=True)
class Row:
    family: str
    table: str
    file: Path
    key: Key
    value: str
    kind: str = SYMBOL
    description: str | None = None


def _lua_list(table: Any) -> list[Any]:
    return [table[i] for i in range(1, len(table) + 1)]


def _table(defs: Any, name: str, rel: Path) -> Any:
    table = defs[name]
    if lua_type(table) != "table":
        fail(f"{rel.as_posix()}: no `{name}` table")
    return table


def _pairs_rows(
    family: str, table: str, rel: Path, entries: Any, value: Callable[[Any], str]
) -> list[Row]:
    """Rows of a list of ``{key, value, ...}`` entries (``value`` maps the raw
    value)."""
    rows = []
    for i, e in enumerate(_lua_list(entries), 1):
        where = f"{rel.name} {table}[{i}]"
        rows.append(Row(family, table, rel, table_key(e[1], where), value(e[2])))
    return rows


def _map_rows(
    family: str, table: str, rel: Path, entries: Any, value: Callable[[Any], str]
) -> list[Row]:
    """Rows of a ``[name] = value`` table, sorted by name."""
    rows = []
    for name, raw in sorted(entries.items(), key=lambda kv: str(kv[0])):
        where = f"{rel.name} {table}[{name!r}]"
        rows.append(Row(family, table, rel, table_key(name, where), value(raw)))
    return rows


def _plain(where: str) -> Callable[[Any], str]:
    return lambda v: table_value(v, where)


def _an_alr(install_dir: Path) -> list[Row]:
    entries, _ = read_tables(install_dir)
    return [
        Row(
            "AN/ALR",
            e.table,
            SYMBOLS if e.table in SYMBOL_TABLES else HARM_IDS,
            e.key,
            e.value,
            SYMBOL if e.table in SYMBOL_TABLES else ALIC,
        )
        for e in entries
    ]


def _ru_elint(install_dir: Path) -> list[Row]:
    defs = run_install_script(install_dir, RU_ELINT)
    v = _plain(RU_ELINT.name)
    return [
        *_pairs_rows(
            "RU ELINT", "symbols", RU_ELINT, _table(defs, "symbols", RU_ELINT), v
        ),
        *_pairs_rows(
            "RU ELINT",
            "symbols_strings",
            RU_ELINT,
            _table(defs, "symbols_strings", RU_ELINT),
            v,
        ),
    ]


def _spo_15(install_dir: Path) -> list[Row]:
    defs = run_install_script(
        install_dir, SPO_15, append="__spo_15_types = SPO_15_types"
    )
    types = _table(defs, "__spo_15_types", SPO_15)
    letters = {int(n): str(letter) for letter, n in types.items()}
    rows = []
    for i, e in enumerate(_lua_list(_table(defs, "spo_15_symbols", SPO_15)), 1):
        where = f"{SPO_15.name} spo_15_symbols[{i}]"
        written = [k for k in ("type", "name") if e[k] is not None]
        if len(written) != 1:
            fail(f"{where}: needs exactly one of `type` and `name`")
        symbol = e["symbol"]
        if symbol not in letters:
            fail(f"{where}: symbol {symbol!r} is none of SPO_15_types")
        rows.append(
            Row(
                "SPO-15",
                "spo_15_symbols",
                SPO_15,
                table_key(e[written[0]], where),
                letters[symbol],
            )
        )
    return rows


def _c130j(install_dir: Path) -> list[Row]:
    defs = run_install_script(install_dir, C130J)
    glyphs = _table(defs, "f_", C130J)
    names: dict[str, str] = {}
    for name, glyph in glyphs.items():
        if str(glyph) in names:
            fail(f"{C130J.as_posix()}: f_ glyph {glyph!r} has two names")
        names[str(glyph)] = str(name)

    def value(raw: Any) -> str:
        glyph = table_value(raw, C130J.name)
        if glyph not in names:
            fail(f"{C130J.as_posix()}: value {glyph!r} is no f_ glyph")
        return names[glyph]

    return [
        *_pairs_rows(
            "C-130J CDMS", "symbols", C130J, _table(defs, "symbols", C130J), value
        ),
        *_map_rows(
            "C-130J CDMS",
            "symbols_strings",
            C130J,
            _table(defs, "symbols_strings", C130J),
            value,
        ),
    ]


def _rwr_codes_table(
    install_dir: Path, rel: Path, family: str, field: str
) -> list[Row]:
    """A module's ``rwr_codes`` (``[unit type] = {<field>, desc, ...}``)."""
    defs = run_install_script(install_dir, rel, wrap=False)
    rows = []
    for name, entry in sorted(
        _table(defs, "rwr_codes", rel).items(), key=lambda kv: str(kv[0])
    ):
        where = f"{rel.name} rwr_codes[{name!r}]"
        if lua_type(entry) != "table" or entry[field] is None:
            fail(f"{where}: no `{field}`")
        desc = entry["desc"]
        rows.append(
            Row(
                family,
                "rwr_codes",
                rel,
                table_key(name, where),
                table_value(entry[field], where),
                description=str(desc) if isinstance(desc, str) and desc else None,
            )
        )
    return rows


def _f15e(install_dir: Path) -> list[Row]:
    return _rwr_codes_table(install_dir, F15E, "F-15E ALR-56C", "code")


def _m2000c(install_dir: Path) -> list[Row]:
    return _rwr_codes_table(install_dir, M2000C, "M-2000C SERVAL", "symb")


@dataclass(frozen=True)
class Family:
    name: str
    slug: str
    files: tuple[Path, ...]
    read: Callable[[Path], list[Row]]
    module: bool = False  # optional: skipped when the module is not installed


FAMILIES = (
    Family("AN/ALR", "an-alr", (SYMBOLS, HARM_IDS), _an_alr),
    Family("RU ELINT", "ru-elint", (RU_ELINT,), _ru_elint),
    Family("SPO-15", "spo-15", (SPO_15,), _spo_15),
    Family("C-130J CDMS", "c-130j-cdms", (C130J,), _c130j, module=True),
    Family("F-15E ALR-56C", "f-15e-alr-56c", (F15E,), _f15e, module=True),
    Family("M-2000C SERVAL", "m-2000c-serval", (M2000C,), _m2000c, module=True),
)


def read_rows(install_dir: Path) -> list[Row]:
    """Every table entry of every family the install has, in family and file
    order."""
    rows: list[Row] = []
    for family in FAMILIES:
        missing = [f for f in family.files if not (install_dir / f).is_file()]
        if missing and family.module:
            warn(
                f"RWR codes: {family.name} skipped, no {missing[0].as_posix()} "
                "(module not installed)"
            )
            continue
        rows += family.read(install_dir)
    return rows


def _key_text(key: Key) -> str:
    if key.name is not None:
        return key.name
    assert key.ident is not None
    return key.ident


def threats_by_unit(threats: Mapping[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Unit type -> the threat ids whose unit or components include it."""
    out: dict[str, set[str]] = {}
    for tid, t in threats.items():
        units = {c["unit"] for c in t.get("components", [])}
        if "unit" in t:
            units.add(t["unit"])
        for u in units:
            out.setdefault(u, set()).add(tid)
    return {u: sorted(ts) for u, ts in out.items()}


def build_rwr_codes(
    rows: list[Row],
    unit_types: set[str],
    weapon_ids: set[str],
    ids: WsTypeIds,
    threats: Mapping[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    slugs = {f.name: f.slug for f in FAMILIES}
    units_by = ids.by_tuple("units")
    projs_by = ids.by_tuple("projectiles")
    by_unit = threats_by_unit(threats)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _key_text(row.key)
        base = f"{slugs[row.family]}:{row.table}:{key}:{row.value}"
        rid, n = base, 1
        while rid in out:
            n += 1
            rid = f"{base}#{n}"
        units, projs = resolve(row.key, unit_types, weapon_ids, units_by, projs_by)
        rec: dict[str, Any] = {
            "id": rid,
            "family": row.family,
            "kind": row.kind,
            "value": row.value,
            "sourceFile": row.file.as_posix(),
            "sourceTable": row.table,
            "key": key,
            "keyType": "string" if row.key.name is not None else "global",
        }
        if row.key.tuple is not None:
            rec["wsType"] = list(row.key.tuple)
        if row.description is not None:
            rec["description"] = row.description
        threat_ids = sorted({t for u in units for t in by_unit.get(u, [])})
        for field, values in (
            ("units", sorted(set(units))),
            ("weapons", sorted(set(projs))),
            ("threats", threat_ids),
        ):
            if values:
                rec[field] = values
        out[rid] = rec
    return out


def summary(records: Mapping[str, dict[str, Any]]) -> list[str]:
    """Per family: rows, rows joining no unit type or weapon, rows with an
    HTS class."""
    counts: dict[str, list[int]] = {}
    for r in records.values():
        c = counts.setdefault(r["family"], [0, 0, 0])
        c[0] += 1
        if not r.get("units") and not r.get("weapons"):
            c[1] += 1
        if "htsClass" in r:
            c[2] += 1
    return [
        f"RWR codes {family}: {n} rows, {unjoined} joining no unit type or "
        f"weapon, {hts} with an HTS class"
        for family, (n, unjoined, hts) in counts.items()
    ]


def hts_classes(
    table: list[dict[str, Any]],
    unit_types: set[str],
    records: Mapping[str, dict[str, Any]],
) -> dict[str, int]:
    """Unit type -> HTS class from the overlay ``table`` (see overlays.yaml),
    checked: every unit is a unit type in one class whose AN/ALR symbol is the
    row's ``dcsSymbol`` or else ``had``."""
    symbols: dict[str, set[str]] = {}
    for r in records.values():
        if r["family"] == "AN/ALR" and r["kind"] == SYMBOL:
            for u in r.get("units", []):
                symbols.setdefault(u, set()).add(r["value"])
    out: dict[str, int] = {}
    problems: list[str] = []
    for row in table:
        where = f"rwr_codes/htsClass {row.get('name')!r}"
        cls, units = row.get("class"), row.get("units")
        if not isinstance(cls, int) or not isinstance(units, list) or not units:
            fail(f"{where}: needs an integer `class` and a list of `units`")
        expected = str(row.get("dcsSymbol", row.get("had")))
        for u in units:
            if u not in unit_types:
                problems.append(f"{where}: {u!r} is no unit type")
            elif u not in symbols:
                problems.append(f"{where}: no AN/ALR symbol entry names {u!r}")
            elif symbols[u] != {expected}:
                problems.append(
                    f"{where}: {u!r} has AN/ALR symbol {sorted(symbols[u])}, "
                    f"not {expected!r}"
                )
            if out.setdefault(u, cls) != cls:
                problems.append(f"{where}: {u!r} is in classes {out[u]} and {cls}")
    if problems:
        fail("stale or wrong HTS class overlay: " + "; ".join(problems))
    return out


def _stamp(record: dict[str, Any], path: str) -> None:
    record.setdefault("_source", {})[path] = HAND_AUTHORED


def apply_hts_classes(
    classes: Mapping[str, int],
    records: Mapping[str, dict[str, Any]],
    threats: Mapping[str, dict[str, Any]],
) -> list[str]:
    """Set ``htsClass`` (see the module docstring); the AN/ALR rows naming
    units of several classes, or classified and unclassified units, are
    returned and left without one."""
    mixed = []
    for rid, r in records.items():
        units = r.get("units", [])
        if r["family"] != "AN/ALR" or not units:
            continue
        found = {classes.get(u) for u in units}
        if found == {None}:
            continue
        if len(found) > 1:
            mixed.append(f"{rid}: {dict(sorted((u, classes.get(u)) for u in units))}")
            continue
        r["htsClass"] = found.pop()
        _stamp(r, "htsClass")
    for t in threats.values():
        if t.get("unit") in classes:
            t["htsClass"] = classes[t["unit"]]
            _stamp(t, "htsClass")
        for c in t.get("components", []):
            if c["unit"] in classes:
                c["htsClass"] = classes[c["unit"]]
                _stamp(c, "htsClass")
    return mixed
