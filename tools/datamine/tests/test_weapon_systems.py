"""Surface-unit ``weaponSystems`` from DCS ``WS``/``LN``/``PL`` tables, in the
shape the dump hook writes once GT_t proxy launchers carry their inherited
fields."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import entity_schema

from tools.datamine.check_refs import check_refs
from tools.datamine.dcs_constants import Constants
from tools.datamine.extract_units import (
    RawUnits,
    build_surface,
    fire_control,
    name_reporting,
    weapon_system_summary,
    weapon_systems,
)
from tools.datamine.overlays import Overlays

WEAPONS = {"9M331", "SM_2", "HQ-7"}
BY_RESOURCE = {"weapons.missiles.SM_2": "SM_2"}

# Tor 9A331 as read from a dump: WS mixes numbered systems with named fields;
# LN[1] is the proxy-expanded _9A330 template (distanceMax, ammo_capacity, the
# full ammunition tuple with slot 4 translated).
TOR: dict[str, Any] = {
    "type": "Tor 9A331",
    "WS": {
        "1": {
            "LN": [
                {
                    "BR": [{"connector_name": "POINT_ROCKET_01"}],
                    "PL": [
                        {
                            "ammo_capacity": 8,
                            "name_ammunition": "9M331",
                            "type_ammunition": [4, 4, 34, "9M331"],
                        }
                    ],
                    "distanceMax": 12000,
                    "distanceMin": 1500,
                    "reactionTime": 6,
                    "sensor": {},
                    "type": 4,
                }
            ],
            "angles": [[3.14, -3.14, -0.07, 1.48]],
        },
        "maxTargetDetectionRange": 25000,
        "radar_type": 104,
    },
}


def _ln(**fields: Any) -> dict[str, Any]:
    return {"sensor": {}, **fields}


# A HQ-7 style unit: a tracking channel (LN without PL), a missile launcher,
# then a gun with two shell belts and a WS-level range.
MIXED: dict[str, Any] = {
    "type": "MIXED",
    "WS": {
        "1": {
            "LN": [_ln(distanceMax=20000, max_trg_alt=5500, min_trg_alt=10, type=102)]
        },
        "2": {
            "LN": [
                _ln(
                    PL=[{"type_ammunition": [4, 4, 34, "HQ-7"], "ammo_capacity": 4}],
                    distanceMax=12000,
                    distanceMin=500,
                    max_trg_alt=5500,
                    min_trg_alt=15,
                )
            ]
        },
        "3": {
            "LN": [
                _ln(
                    PL=[
                        {"ammo_capacity": 500, "shell_name": ["30mm_HE", "30mm_AP"]},
                        {"ammo_capacity": 250, "shell_name": ["30mm_HE"]},
                    ]
                )
            ],
            "distanceMin": 10,
            "distanceMax": 4000,
        },
        "fire_on_march": True,
    },
}

# Ship with a resource-name ammunition, an unresolvable tuple and the
# {[4] = "Redacted"} shape of dumps before the proxy fix.
SHIP: dict[str, Any] = {
    "type": "CG",
    "WS": [
        {"LN": [_ln(PL=[{"type_ammunition": "weapons.missiles.SM_2"}])]},
        {"LN": [_ln(PL=[{"type_ammunition": [4, 4, 34, "Redacted"]}])]},
        {"LN": [_ln(PL=[{"type_ammunition": {"4": "Redacted"}}])]},
        {"LN": [_ln(PL=[{"type_ammunition": [4, 4, 34, "NOT_A_WEAPON"]}])]},
    ],
}


def test_proxy_expanded_launcher() -> None:
    assert weapon_systems(TOR, WEAPONS, BY_RESOURCE) == [
        {
            "ws": 1,
            "ln": 1,
            "launcherType": 4,
            "weapons": ["9M331"],
            "payloads": [{"weapon": "9M331", "ammoName": "9M331", "ammoCapacity": 8}],
            "rMinKm": 1.5,
            "rMaxKm": 12.0,
            "reactionTimeS": 6,
            "barrels": 1,
            "sectorsRad": [[3.14, -3.14, -0.07, 1.48]],
        }
    ]


def test_every_launcher_with_per_payload_ammunition() -> None:
    channel, missile, gun = weapon_systems(MIXED, WEAPONS, BY_RESOURCE)
    assert channel == {
        "ws": 1,
        "ln": 1,
        "launcherType": 102,
        "rMaxKm": 20.0,
        "hMinM": 10,
        "hMaxM": 5500,
    }
    assert missile["weapons"] == ["HQ-7"]
    assert missile["payloads"] == [{"weapon": "HQ-7", "ammoCapacity": 4}]
    assert (missile["ws"], missile["rMinKm"], missile["hMinM"]) == (2, 0.5, 15)
    assert gun == {
        "ws": 3,
        "ln": 1,
        "gunAmmo": ["30mm_AP", "30mm_HE"],
        "payloads": [
            {"gunAmmo": ["30mm_AP", "30mm_HE"], "ammoCapacity": 500},
            {"gunAmmo": ["30mm_HE"], "ammoCapacity": 250},
        ],
        "rMinKm": 0.01,
        "rMaxKm": 4.0,
    }


def test_resource_names_resolve_and_unknown_ammunition_is_dropped() -> None:
    systems = weapon_systems(SHIP, WEAPONS, BY_RESOURCE)
    assert [ws.get("weapons") for ws in systems] == [["SM_2"], None, None, None]
    assert [ws["payloads"] for ws in systems[1:]] == [[{}], [{}], [{}]]


def test_pre_fix_dump_shape_names_nothing() -> None:
    # A proxy launcher from a dump taken before the serializer flattened
    # proxies: only the raw nested tables survive.
    old = {
        "WS": {
            "1": {"LN": [{"BR": [{}], "PL": [{"type_ammunition": {"4": "Redacted"}}]}]}
        }
    }
    assert weapon_systems(old, WEAPONS, BY_RESOURCE) == [
        {"ws": 1, "ln": 1, "payloads": [{}], "barrels": 1}
    ]
    assert weapon_systems({"type": "no WS"}, WEAPONS, BY_RESOURCE) == []


def test_launcher_fields() -> None:
    rec = {
        "type": "SAM",
        "WS": {
            "1": {
                "name": "WS name",
                "display_name": "WS display",
                "omegaY": 1,
                "omegaZ": 0.5,
                "LN": [
                    _ln(
                        type=4,
                        max_number_of_missile_channels=2,
                        depends_on_unit=[
                            [["SR"]],
                            [["self", 2], ["TR", 1]],
                            [["none"]],
                        ],
                        reactionTime=4,
                        launch_delay=5,
                        ECM_K=0.65,
                        reflection_limit=0.18,
                        beamWidth=1.5,
                        frequencyRange=[6e9, 9e9],
                        external_tracking_awacs=True,
                        maxShootingSpeed=0,
                        BR=[{}, {}, {}, {}],
                        PL=[
                            {
                                "name_ammunition": "9M38",
                                "shell_display_name": "9M38 display",
                                "ammo_capacity": 4,
                                "portionAmmoCapacity": 2,
                                "reload_time": 780,
                                "portion_reload_time": 20,
                                "shot_delay": 0.1,
                            }
                        ],
                    ),
                    _ln(name="LN name", max_number_of_missiles_channels=1),
                ],
            }
        },
    }
    first, second = weapon_systems(rec, WEAPONS, BY_RESOURCE)
    assert first == {
        "ws": 1,
        "ln": 1,
        "launcherType": 4,
        "name": "WS name",
        "displayName": "WS display",
        "payloads": [
            {
                "ammoName": "9M38",
                "ammoDisplayName": "9M38 display",
                "ammoCapacity": 4,
                "portionAmmoCapacity": 2,
                "reloadTimeS": 780,
                "portionReloadTimeS": 20,
                "shotDelayS": 0.1,
            }
        ],
        "missileChannels": 2,
        "dependsOn": [
            [{"unit": "SR"}],
            [{"selfWs": 2}, {"unit": "TR", "ws": 1}],
            [{"none": True}],
        ],
        "reactionTimeS": 4,
        "launchDelayS": 5,
        "ecmK": 0.65,
        "reflectionLimit": 0.18,
        "beamWidthRad": 1.5,
        "frequencyRangeHz": [6e9, 9e9],
        "externalTrackingAwacs": True,
        "maxShootingSpeed": 0,
        "barrels": 4,
        "slewRateRadS": {"yaw": 1, "pitch": 0.5},
    }
    assert (second["name"], second["missileChannels"]) == ("LN name", 1)


def test_missile_channel_spellings_must_agree() -> None:
    rec = {
        "WS": [
            {
                "LN": [
                    _ln(
                        max_number_of_missiles_channels=1,
                        max_number_of_missile_channels=2,
                    )
                ]
            }
        ]
    }
    with pytest.raises(SystemExit):
        weapon_systems(rec, WEAPONS, BY_RESOURCE)


def test_unreadable_launcher_fields_are_reported() -> None:
    rec = {
        "type": "X",
        "WS": [
            {"LN": [_ln(depends_on_unit=3, frequencyRange=[1])]},
            {"LN": [_ln(depends_on_unit=[[[["self", 2]]]])]},
        ],
    }
    problems: list[str] = []
    systems = weapon_systems(rec, WEAPONS, BY_RESOURCE, problems)
    assert systems == [{"ws": 1, "ln": 1}, {"ws": 2, "ln": 1}]
    assert problems == [
        "X: unreadable launcher field(s) left out: WS[1].LN[1].depends_on_unit 3; "
        "WS[1].LN[1].frequencyRange [1]; "
        "WS[2].LN[1].depends_on_unit [[[['self', 2]]]]"
    ]


def test_fire_control() -> None:
    constants = Constants({"wsType": {"wsType_Radar_Miss": 102, "wsType_Missile": 4}})
    rec = {
        "WS": {
            "maxTargetDetectionRange": 25000,
            "radar_type": 102,
            "fire_on_march": False,
            "isDetector": True,
        }
    }
    assert fire_control(rec, constants) == {
        "fireOnMove": False,
        "isDetector": True,
        "maxTargetDetectionRangeM": 25000,
        "radarType": 102,
        "radarTypeName": "wsType_Radar_Miss",
    }
    assert fire_control({"WS": {"radar_type": 109}}, constants) == {"radarType": 109}
    assert fire_control({"WS": []}, constants) is None


def _raw() -> RawUnits:
    return RawUnits(
        by_category={
            "Cars": {"Tor 9A331": TOR, "MIXED": MIXED, "TRUCK": {"type": "TRUCK"}},
            "Ships": {"CG": SHIP},
            "Personnel": {"P": {"type": "P", "WS": TOR["WS"]}},
        }
    )


def test_build_surface_attaches_weapon_systems() -> None:
    surface = build_surface(_raw(), WEAPONS, BY_RESOURCE)
    vehicles = surface["ground_vehicles"]
    assert vehicles["Tor 9A331"]["weaponSystems"][0]["weapons"] == ["9M331"]
    assert vehicles["Tor 9A331"]["fireControl"] == {
        "maxTargetDetectionRangeM": 25000,
        "radarType": 104,
    }
    assert len(vehicles["MIXED"]["weaponSystems"]) == 3
    assert vehicles["MIXED"]["fireControl"] == {"fireOnMove": True}
    assert "weaponSystems" not in vehicles["TRUCK"]
    assert len(surface["ships"]["CG"]["weaponSystems"]) == 4
    assert "weaponSystems" not in surface["personnel"]["P"]
    assert weapon_system_summary(surface) == (
        "Surface weapon systems: 8 launcher(s) on 3 unit(s), "
        "7 with a payload, 3 naming a weapon, 4 with a range"
    )


def test_without_weapon_ids_no_weapon_is_named() -> None:
    surface = build_surface(_raw())
    systems = surface["ground_vehicles"]["Tor 9A331"]["weaponSystems"]
    assert systems[0]["payloads"] == [{"ammoName": "9M331", "ammoCapacity": 8}]
    assert "weapons" not in systems[0]


def test_check_refs_follows_weapon_systems() -> None:
    surface = build_surface(_raw(), WEAPONS, BY_RESOURCE)
    surface["ships"]["CG"]["weaponSystems"].append({"weapons": ["GONE"]})
    surface["ships"]["CG"]["weaponSystems"].append(
        {"dependsOn": [[{"unit": "TRUCK"}, {"selfWs": 1}], [{"unit": "NO_UNIT"}]]}
    )
    data: dict[str, dict[str, Any]] = {
        **surface,
        "weapons": {w: {"id": w} for w in WEAPONS},
        "gun_ammo": {"30mm_HE": {"id": "30mm_HE"}},
    }
    report = check_refs(data, entity_schema(), {})
    dangling = sorted(str(r) for r in report.dangling if "weaponSystems" in r.field)
    assert dangling == [
        "ground_vehicles/MIXED.json :: weaponSystems[].gunAmmo[] -> '30mm_AP' [gun_ammo]",
        "ground_vehicles/MIXED.json :: weaponSystems[].payloads[].gunAmmo[] -> '30mm_AP' [gun_ammo]",
        "ships/CG.json :: weaponSystems[].dependsOn[][].unit -> 'NO_UNIT' [units]",
        "ships/CG.json :: weaponSystems[].weapons[] -> 'GONE' [weapons]",
    ]
    report = check_refs(
        data, entity_schema(), {}, {"NO_UNIT": "note", "TRUCK": "now defined"}
    )
    assert [r.value for r in report.upstream] == ["NO_UNIT"]
    assert report.stale_gaps == ["TRUCK"]


def _named(hand: dict[str, str]) -> dict[str, dict[str, dict[str, Any]]]:
    def unit(uid: str, name: str, *attrs: str) -> dict[str, Any]:
        return {"id": uid, "displayName": name, "attributes": list(attrs)}

    surface = {
        "ground_vehicles": {
            "LN": unit("LN", 'SAM SA-11 Buk "Gadfly" LN', "Air Defence"),
            "SR": unit("SR", 'SAM SA-2/3/5 P19 "Flat Face" SR ', "Air Defence"),
            "TRUCK": unit("TRUCK", 'Truck GMC "Jimmy" 6x6', "Trucks"),
            "QF": unit("QF", 'AAA QF 3.7"', "Air Defence"),
            "TWO": unit("TWO", 'SAM "A" "B"', "Air Defence"),
            "PATRIOT": unit("PATRIOT", "SAM Patriot STR", "Air Defence"),
        },
        "ships": {"CG": unit("CG", "CG Ticonderoga", "Air Defence")},
    }
    name_reporting(surface, Overlays([], {("units", "natoReportingName"): hand}))
    return surface


def test_reporting_names_are_air_defence_display_name_quotes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    vehicles = _named({})["ground_vehicles"]
    assert {u: r.get("natoReportingName") for u, r in vehicles.items()} == {
        "LN": "Gadfly",
        "SR": "Flat Face",
        "TRUCK": None,  # a nickname on a unit that is not Air Defence
        "QF": None,  # an inch mark, not a quoted name
        "TWO": None,
        "PATRIOT": None,
    }
    assert "TWO: displayName quotes ['A', 'B']" in capsys.readouterr().err


def test_overlay_fills_unnamed_units() -> None:
    surface = _named({"PATRIOT": "x", "CG": "y"})
    assert surface["ground_vehicles"]["PATRIOT"]["natoReportingName"] == "x"
    assert surface["ships"]["CG"]["_source"] == {"natoReportingName": "hand-authored"}
    assert "_source" not in surface["ground_vehicles"]["LN"]


def test_overlay_overrides_a_quoted_system_name() -> None:
    ln = _named({"LN": "Fire Dome"})["ground_vehicles"]["LN"]
    assert ln["natoReportingName"] == "Fire Dome"
    assert ln["_source"] == {"natoReportingName": "hand-authored"}


@pytest.mark.parametrize(
    ("hand", "why"),
    [
        ({"GONE": "x"}, "'GONE': no ground vehicle or ship"),
        ({"LN": "Gadfly"}, "'LN': DCS already names it 'Gadfly'"),
    ],
)
def test_stale_reporting_name_entries_fail(
    hand: dict[str, str], why: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        _named(hand)
    assert why in capsys.readouterr().err
