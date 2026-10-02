"""DCS numeric constants (``wsType_*``, ``CAT_*``, ``SENSOR_*``, ...) and the
``Entity.*`` enum types generated from them.

A numeric enum field keeps the DCS number and gets a sibling ``<field>Name``
holding the constant's name. The ``FAMILIES`` come from ``_G/__constants__.lua``,
written by the dump hook from the game's ``_G``; a dump without it fails. The
``INSTALL_FAMILIES`` (beacon types and systems, Radio.lua modulation types and
bands) are the numeric globals of the install scripts that define them
(``extract_theatres.install_constants``).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import REPO_ROOT, fail, yaml_key
from .lua_reader import LuaReader, as_dict, as_number

CONSTANTS_FILE = "__constants__.lua"

FAMILIES = ("wsType", "CAT", "SENSOR", "OPTIC_SENSOR", "RADAR", "MODULATION", "country")
INSTALL_FAMILIES = ("BEACON_TYPE", "SystemName", "MODULATIONTYPE", "FrequencyBand")


@dataclass(frozen=True)
class EnumSpec:
    type_name: str
    family: str
    names: tuple[str, ...] | None  # None: every constant of the family
    description: str


ENUMS = (
    EnumSpec(
        "Entity.WsTypeWeaponLevel2",
        "wsType",
        (
            "wsType_Missile",
            "wsType_Bomb",
            "wsType_Shell",
            "wsType_NURS",
            "wsType_Torpedo",
        ),
        "wsType level 2 under wsType_Weapon (`ws_type`/`wsTypeOfWeapon`), per Scripts/Database/wsTypes.lua. Not the scripting-API `Weapon.Category`.",
    ),
    EnumSpec(
        "Entity.LauncherCategory",
        "CAT",
        (
            "CAT_BOMBS",
            "CAT_MISSILES",
            "CAT_ROCKETS",
            "CAT_AIR_TO_AIR",
            "CAT_FUEL_TANKS",
            "CAT_PODS",
            "CAT_SHELLS",
            "CAT_GUN_MOUNT",
            "CAT_CLUSTER_DESC",
            "CAT_SERVICE",
            "CAT_TORPEDOES",
        ),
        "Launcher/projectile `category` (CAT_*).",
    ),
    EnumSpec(
        "Entity.SensorCategory",
        "SENSOR",
        ("SENSOR_OPTICAL", "SENSOR_RADAR", "SENSOR_IRST", "SENSOR_RWR"),
        "Sensor `category` (SENSOR_*).",
    ),
    EnumSpec(
        "Entity.OpticSensorType",
        "OPTIC_SENSOR",
        ("OPTIC_SENSOR_TV", "OPTIC_SENSOR_LLTV", "OPTIC_SENSOR_IR"),
        "Optical sensor `type` (OPTIC_SENSOR_*).",
    ),
    EnumSpec(
        "Entity.RadarType",
        "RADAR",
        ("RADAR_AS", "RADAR_SS", "RADAR_MULTIROLE"),
        "Radar sensor `type` (RADAR_*).",
    ),
    EnumSpec(
        "Entity.UnitRadarType",
        "wsType",
        (
            "wsType_Radar",
            "wsType_Radar_Miss",
            "wsType_Radar_MissGun",
            "wsType_MissGun",
            "wsType_Radar_Gun",
        ),
        "The wsType constants a ground vehicle's or ship's `WS.radar_type` takes.",
    ),
    EnumSpec(
        "Entity.RadioModulation",
        "MODULATION",
        (
            "MODULATION_VOID",
            "MODULATION_AM",
            "MODULATION_FM",
            "MODULATION_AM_AND_FM",
        ),
        "Radio `modulation` (MODULATION_*).",
    ),
    EnumSpec(
        "Entity.BeaconType",
        "BEACON_TYPE",
        None,
        "Beacon `type` (BEACON_TYPE_*), per Scripts/World/Radio/BeaconTypes.lua.",
    ),
    EnumSpec(
        "Entity.RadioModulationType",
        "MODULATIONTYPE",
        None,
        "Terrain Radio.lua frequency modulation (MODULATIONTYPE_*), per Scripts/World/Radio/ModulationTypes.lua; not the aircraft-radio MODULATION_*.",
    ),
    EnumSpec(
        "Entity.FrequencyBand",
        "FrequencyBand",
        None,
        "Terrain Radio.lua frequency band key, per Scripts/World/Radio/FrequencyBands.lua.",
    ),
)
ENUM_BY_TYPE = {e.type_name: e for e in ENUMS}
# wsType level-2 weapon constant -> the wsType constants of its level 3, per
# the level-3 sections of Scripts/Database/wsTypes.lua (`-- wsType_Missile`,
# `-- wsType_Bomb`, `-- wsType_Shell`, `-- wsType_NURS`; the torpedo constants
# are listed there after the missile ones). Level-3 numbers repeat across
# level 2 (10 is wsType_A_Torpedo and wsType_Shell_A), so they name no enum.
WEAPON_LEVEL3 = {
    "wsType_Missile": (
        "wsType_AA_Missile",
        "wsType_AS_Missile",
        "wsType_SA_Missile",
        "wsType_SS_Missile",
        "wsType_AA_TRAIN_Missile",
        "wsType_AS_TRAIN_Missile",
    ),
    "wsType_Bomb": (
        "wsType_Bomb_A",
        "wsType_Bomb_Guided",
        "wsType_Bomb_BetAB",
        "wsType_Bomb_Cluster",
        "wsType_Bomb_Antisubmarine",
        "wsType_Bomb_ODAB",
        "wsType_Bomb_Fire",
        "wsType_Bomb_Nuclear",
        "wsType_Bomb_Lighter",
    ),
    "wsType_Shell": ("wsType_Shell_A",),
    "wsType_NURS": ("wsType_Container", "wsType_Rocket"),
    "wsType_Torpedo": ("wsType_A_Torpedo", "wsType_S_Torpedo"),
}
RADAR_TYPE = "Entity.UnitRadarType"
COUNTRY_TYPE = "country.id"

TYPES_DIR = REPO_ROOT / "dcs-world-schema" / "types"
GENERATED_SCHEMA = TYPES_DIR / "entities" / "Constants.generated.enum.yaml"
# The scripting API's country.id / country.name, as DCS builds them from
# country.names (Scripts/ScriptingSystem.lua).
COUNTRY_SCHEMA = TYPES_DIR / "country.enum.yaml"
# Scripting API enums of install constants (ActivateBeacon `type`, `system`).
BEACON_SCHEMA = TYPES_DIR / "Beacon.generated.enum.yaml"
_GENERATED = (
    "Generated by tools/datamine/extract.py from DCS constants (_G dump); do not edit."
)
_GENERATED_INSTALL = (
    "Generated by tools/datamine/extract.py from the DCS install scripts; do not edit."
)


@dataclass
class Constants:
    values: dict[str, dict[str, int]]  # family -> constant name -> number
    unresolved: Counter[tuple[str, Any]] = field(default_factory=Counter)

    def value(self, family: str, name: str) -> int | None:
        return self.values.get(family, {}).get(name)

    def enum_values(self, type_name: str) -> dict[str, int]:
        """Scoped ``{name: number}`` of a generated enum type (or country.id)."""
        if type_name == COUNTRY_TYPE:
            return dict(self.values.get("country", {}))
        spec = ENUM_BY_TYPE[type_name]
        family = self.values.get(spec.family, {})
        if spec.names is None:
            return dict(family)
        return {n: family[n] for n in spec.names if n in family}

    def name(self, type_name: str, number: Any) -> str | None:
        """The constant name for ``number``, or None (counted as unresolved)
        when no name or several names carry it."""
        names = [n for n, v in self.enum_values(type_name).items() if v == number]
        if len(names) == 1:
            return names[0]
        self.unresolved[(type_name, number)] += 1
        return None

    def level3_name(self, level2_name: str, number: Any) -> str | None:
        """The ``WEAPON_LEVEL3`` constant of ``level2_name`` carrying ``number``,
        or None (counted as unresolved)."""
        family = self.values.get("wsType", {})
        names = [
            n for n in WEAPON_LEVEL3.get(level2_name, ()) if family.get(n) == number
        ]
        if len(names) == 1:
            return names[0]
        self.unresolved[(f"wsType level 3 under {level2_name}", number)] += 1
        return None

    def set_pair(
        self, record: dict[str, Any], key: str, type_name: str, number: Any
    ) -> bool:
        """``record[key] = number`` and ``record[key + "Name"]`` = its constant
        name; neither is set when the number does not resolve."""
        if as_number(number) is None:
            return False
        name = self.name(type_name, number)
        if name is None:
            return False
        record[key] = int(number)
        record[f"{key}Name"] = name
        return True

    def manifest(self) -> list[dict[str, Any]]:
        return [
            {"family": f, "count": len(self.values[f])}
            for f in (*FAMILIES, *INSTALL_FAMILIES)
            if f in self.values
        ]


def load_constants(reader: LuaReader, g_dir: Path) -> Constants:
    path = g_dir / CONSTANTS_FILE
    if not path.is_file():
        fail(
            f"no {CONSTANTS_FILE} in {g_dir}: dump predates constant capture; "
            "re-dump with the current hook (task datamine)"
        )
    dumped = reader.read_file(path)
    if dumped is None:
        fail(f"{path} failed to parse: {reader.stats.failures[-1][1]}")
    values = {
        family: {
            str(k): int(v)
            for k, v in as_dict(as_dict(dumped).get(family)).items()
            if as_number(v) is not None
        }
        for family in FAMILIES
    }
    missing = [f for f, v in values.items() if not v]
    if missing:
        fail(f"{path} has no {missing} constants")
    return Constants(values)


def _enum_block(
    type_name: str, description: str, values: list[tuple[str, str]]
) -> list[str]:
    """The YAML lines of one ``kind: enum`` type (keys and values as written)."""
    return [
        f"  {type_name}:",
        "    kind: enum",
        f"    description: {json.dumps(description)}",
        "    values:",
        *(f"      {k}: {v}" for k, v in values),
    ]


def render_schema(constants: Constants) -> str:
    """The generated enum YAML (deterministic; values ordered by number, name)."""
    out = ["globals: {}", "", "types:"]
    for spec in ENUMS:
        values = constants.enum_values(spec.type_name)
        suffix = _GENERATED if spec.family in FAMILIES else _GENERATED_INSTALL
        ordered = sorted(values.items(), key=lambda kv: (kv[1], kv[0]))
        out += _enum_block(
            spec.type_name,
            f"{spec.description} {suffix}",
            [(yaml_key(name), str(num)) for name, num in ordered],
        )
        out.append("")
    return "\n".join(out[:-1]) + "\n"


def render_country_schema(constants: Constants) -> str:
    """``country.id`` (name -> id) and its exact inverse ``country.name``."""
    ids = constants.values["country"]
    by_id = sorted(ids.items(), key=lambda kv: kv[1])
    if len({i for _, i in by_id}) != len(by_id):
        fail(f"country constants share an id: {by_id}")
    id_desc = (
        "Enumerator for country identifiers, used to specify nation affiliation "
        f"for units and coalition forces in the DCS World. {_GENERATED}"
    )
    name_desc = (
        "Enumerator for retrieving country names from numeric identifiers, "
        f"providing a reverse lookup of country.id values. {_GENERATED}"
    )
    return (
        "\n".join(
            [
                "globals: {}",
                "",
                "types:",
                *_enum_block(
                    "country.id",
                    id_desc,
                    [(yaml_key(n, spaces=True), str(i)) for n, i in by_id],
                ),
                *_enum_block(
                    "country.name",
                    name_desc,
                    [(str(i), json.dumps(n)) for n, i in by_id],
                ),
            ]
        )
        + "\n"
    )


def render_beacon_schema(constants: Constants) -> str:
    """``BeaconType`` (the values of ``Entity.BeaconType``) and
    ``BeaconSystemName`` (``SystemName``) under their API names."""
    out = ["globals: {}", "", "types:"]
    for name, values, description in (
        (
            "BeaconType",
            constants.enum_values("Entity.BeaconType"),
            "Beacon types (`ActivateBeacon` `type`), per "
            "Scripts/World/Radio/BeaconTypes.lua.",
        ),
        (
            "BeaconSystemName",
            constants.values.get("SystemName", {}),
            "Beacon systems (`ActivateBeacon` `system`): transmitter power, "
            "antenna pattern and signal, per Scripts/World/Radio/BeaconSites.lua.",
        ),
    ):
        if not values:
            fail(f"no install constants for {name}")
        ordered = sorted(values.items(), key=lambda kv: (kv[1], kv[0]))
        out += _enum_block(
            name,
            f"{description} {_GENERATED_INSTALL}",
            [(n, str(v)) for n, v in ordered],
        )
        out.append("")
    return "\n".join(out[:-1]) + "\n"


def generated_schemas(constants: Constants) -> dict[Path, str]:
    """Every schema file generated from the constants, by path."""
    return {
        GENERATED_SCHEMA: render_schema(constants),
        COUNTRY_SCHEMA: render_country_schema(constants),
        BEACON_SCHEMA: render_beacon_schema(constants),
    }
