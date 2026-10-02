"""Terrain Lua evaluation, the projection fit and the theatre/beacon/airbase build."""

from pathlib import Path
from typing import Any

import pytest
from conftest import write

from tools.datamine import extract_theatres, overlays, tmerc
from tools.datamine.dcs_constants import Constants

TRUE = tmerc.Projection(33.0, 0.9996, -99517.0, -4998115.0)

_BEACON_TYPES = """
package.path = package.path..';./Scripts/?.lua;'
local utils = require('utils')
BEACON_TYPE_NULL = 0
BEACON_TYPE_TACAN = 4
BEACON_TYPE_ILS_LOCALIZER = 16640
BEACON_TYPE_ILS_GLIDESLOPE = 16896
BEACON_DISABLED = 0
function pow2(x) return math.pow(x, 2) end
"""


def _beacon(i: int, lat: float, lon: float, btype: str, extra: str = "") -> str:
    x, z = TRUE.to_map(lat, lon)
    return f"""
    {{
        display_name = _('Field');
        beaconId = 'airfield{i}_0';
        type = {btype};
        callsign = 'B{i}';
        frequency = 977000000.000000;
        position = {{ {x!r}, 10.0, {z!r} }};
        direction = 0.0;
        positionGeo = {{ latitude = {lat!r}, longitude = {lon!r} }};
        sceneObjects = {{'t:1'}};{extra}
    }};"""


def _install(tmp_path: Path, beacons: list[str]) -> Path:
    root = tmp_path / "dcs"
    write(root / "Scripts/Database/wsTypes.lua", "wsType_Air = 1\n")
    write(root / "Scripts/World/Radio/BeaconTypes.lua", _BEACON_TYPES)
    write(
        root / "Scripts/World/Radio/BeaconSites.lua",
        "dofile('Scripts/World/Radio/BeaconTypes.lua')\nX = pow2(3)\n"
        "SystemName = {TACAN = 3}\n",
    )
    write(
        root / "Scripts/World/Radio/ModulationTypes.lua",
        "MODULATIONTYPE_AM = 0\nMODULATIONTYPE_FM = 1\n",
    )
    write(
        root / "Scripts/World/Radio/FrequencyBands.lua",
        "HF = 0\nVHF_LOW = 1\nVHF_HI = 2\nUHF = 3\n",
    )
    terrain = root / "Mods/terrains/Test"
    write(
        terrain / "entry.lua",
        """if not USE_TERRAIN4 then return end
theatre = {['id'] = "TestMap"; ['localizedName'] = "Test Map";
  ['Skins'] = {{name = _("Test"), dir = "Theme"}}, ['path'] = current_mod_path}
declare_plugin("TestMap", theatre)
plugin_done()
""",
    )
    write(
        terrain / "Beacons.lua",
        """dofile('Scripts/Database/wsTypes.lua')
dofile('Scripts/World/Radio/BeaconTypes.lua')
dofile('Scripts/World/Radio/BeaconSites.lua')
local gettext = require("i_18n")
local       _ = gettext.translate
beacons = {"""
        + "".join(beacons)
        + "\n}\n",
    )
    write(
        terrain / "radio.lua",
        """dofile('Scripts/World/Radio/ModulationTypes.lua')
dofile('Scripts/World/Radio/FrequencyBands.lua')
local gettext = require("i_18n")
local       _ = gettext.translate
radio = {
    {
        radioId = 'airfield1_0';
        role = {"ground", "tower"};
        callsign = {{["nato"] = {_("Alpha"), "Alpha"}}, {["ussr"] = {_("Bravo"), "Bravo"}}};
        frequency = {[VHF_LOW] = {MODULATIONTYPE_FM, 38400000.0}, [VHF_HI] = {MODULATIONTYPE_AM, 121000000.0}, [UHF] = {MODULATIONTYPE_AM, 250000000.0}};
    };
    {
        radioId = 'airfield99_0';
        role = {"approach"};
        callsign = {{["common"] = {_("Zulu"), "Zulu"}}};
        frequency = {};
    };
}
""",
    )
    return root


def _grid(n: int = 12) -> list[tuple[float, float]]:
    return [(42.0 + (i % 4) * 0.5, 38.0 + (i // 4) * 0.7) for i in range(n)]


def _constants(root: Path) -> Constants:
    return Constants(dict(extract_theatres.install_constants(root)))


def test_fit_recovers_known_projection() -> None:
    pts = [(*TRUE.to_map(lat, lon), lat, lon) for lat, lon in _grid()]
    f = tmerc.fit(pts)
    p = f.projection
    assert p.central_meridian == pytest.approx(33.0, abs=1e-6)
    assert p.scale_factor == pytest.approx(0.9996, abs=1e-9)
    assert p.false_easting == pytest.approx(-99517.0, abs=1e-3)
    assert p.false_northing == pytest.approx(-4998115.0, abs=1e-3)
    assert f.max_m < 1e-3
    lat, lon = p.to_geo(*TRUE.to_map(43.1, 39.2))
    assert (lat, lon) == pytest.approx((43.1, 39.2), abs=1e-9)


def test_build_from_synthetic_terrain(tmp_path: Path) -> None:
    beacons = [
        _beacon(i + 1, lat, lon, "BEACON_TYPE_TACAN", "\n        channel = 16;")
        for i, (lat, lon) in enumerate(_grid())
    ]
    beacons.append(_beacon(1, 42.01, 38.01, "BEACON_TYPE_ILS_LOCALIZER"))
    beacons[-1] = beacons[-1].replace("airfield1_0", "airfield1_1")
    beacons.append(_beacon(1, 42.02, 38.01, "BEACON_TYPE_ILS_GLIDESLOPE"))
    beacons[-1] = beacons[-1].replace("airfield1_0", "airfield1_2")
    root = _install(tmp_path, beacons)
    series, report = extract_theatres.build(root, _constants(root), overlays.load(None))

    theatre = series["theatres"]["TestMap"]
    assert theatre["displayName"] == "Test Map"
    assert theatre["directory"] == "Test"
    proj = theatre["projection"]
    assert proj["centralMeridian"] == pytest.approx(33.0)
    assert proj["fit"]["points"] == 14
    assert proj["fit"]["maxResidualM"] < 0.2
    assert report and report[0].startswith("TestMap")

    tacan = series["beacons"]["TestMap.airfield1_0"]
    assert tacan["typeName"] == "BEACON_TYPE_TACAN" and tacan["type"] == 4
    assert tacan["channel"] == 16 and tacan["frequencyHz"] == 977000000
    assert tacan["airbase"] == "TestMap.1"
    assert tacan["displayName"] == "Field"

    ils = series["navaids"]["TestMap.ILS.airfield1_1"]
    assert ils["equipment"] == ["TestMap.airfield1_1", "TestMap.airfield1_2"]

    base = series["airbases"]["TestMap.1"]
    assert base["navaids"] == ["TestMap.ILS.airfield1_1"]
    (svc,) = base["services"]
    assert svc["serviceTypes"] == ["GND", "TWR"]
    assert svc["callsigns"] == [
        {"faction": "nato", "callsign": "Alpha"},
        {"faction": "ussr", "callsign": "Bravo"},
    ]
    assert [c["bandName"] for c in svc["channels"]] == ["VHF_LOW", "VHF_HI", "UHF"]
    assert svc["channels"][0]["modulationName"] == "MODULATIONTYPE_FM"
    radio_only = series["airbases"]["TestMap.99"]
    assert "channels" not in radio_only["services"][0]
    assert "beacons" not in radio_only


def test_fit_residual_fails(tmp_path: Path) -> None:
    beacons = [
        _beacon(i + 1, lat, lon, "BEACON_TYPE_TACAN")
        for i, (lat, lon) in enumerate(_grid())
    ]
    # A 0.0001 deg latitude error (~11 m) at one beacon.
    beacons[1] = beacons[1].replace("latitude = 42.5,", "latitude = 42.5001,")
    root = _install(tmp_path, beacons)
    with pytest.raises(SystemExit):
        extract_theatres.build(root, _constants(root), overlays.load(None))


def test_too_few_points_fail(tmp_path: Path) -> None:
    beacons = [
        _beacon(i + 1, lat, lon, "BEACON_TYPE_TACAN")
        for i, (lat, lon) in enumerate(_grid(4))
    ]
    root = _install(tmp_path, beacons)
    with pytest.raises(SystemExit):
        extract_theatres.build(root, _constants(root), overlays.load(None))


def test_unknown_require_fails(tmp_path: Path) -> None:
    root = _install(tmp_path, [])
    write(root / "Mods/terrains/Test/Beacons.lua", "require('lfs')\nbeacons = {}\n")
    with pytest.raises(SystemExit):
        extract_theatres.build(root, _constants(root), overlays.load(None))


def _eq(bid: str, kind: str, direction: float, channel: int = 26) -> dict[str, Any]:
    return {
        "id": f"T.{bid}",
        "beaconId": bid,
        "typeName": f"BEACON_TYPE_PRMG_{kind}",
        "airbase": "T.15",
        "channel": channel,
        "direction": direction,
    }


def test_prmg_pairs_by_direction() -> None:
    beacons = [
        _eq("airfield15_0", "LOCALIZER", 39.519804),
        _eq("airfield15_3", "LOCALIZER", -140.480217),
        _eq("airfield15_7", "GLIDESLOPE", -141.000023),
        _eq("airfield15_6", "GLIDESLOPE", 38.99997),
    ]
    out = extract_theatres._navaids(beacons, "T")
    assert sorted(out) == ["T.PRMG.airfield15_0", "T.PRMG.airfield15_3"]
    a = out["T.PRMG.airfield15_0"]
    assert a["equipment"] == ["T.airfield15_0", "T.airfield15_6"]
    assert a["grouping"] == "direction"
    assert a["directionDeltaDeg"] == pytest.approx(0.519834)
    assert out["T.PRMG.airfield15_3"]["equipment"][1] == "T.airfield15_7"


def test_prmg_single_pair_is_exact() -> None:
    out = extract_theatres._navaids(
        [_eq("a_0", "LOCALIZER", 73.0), _eq("a_1", "GLIDESLOPE", 73.85)], "T"
    )
    (rec,) = out.values()
    assert rec["grouping"] == "channel"
    assert rec["directionDeltaDeg"] == pytest.approx(0.85)


@pytest.mark.parametrize(
    "dirs",
    [
        # beyond tolerance
        [
            (10.0, "LOCALIZER"),
            (190.0, "LOCALIZER"),
            (30.0, "GLIDESLOPE"),
            (170.0, "GLIDESLOPE"),
        ],
        # not one-to-one: both localizers nearest the same glideslope
        [
            (10.0, "LOCALIZER"),
            (12.0, "LOCALIZER"),
            (11.0, "GLIDESLOPE"),
            (190.0, "GLIDESLOPE"),
        ],
        # unequal counts
        [(10.0, "LOCALIZER"), (10.0, "GLIDESLOPE"), (190.0, "GLIDESLOPE")],
    ],
)
def test_ambiguous_direction_pairing_stays_standalone(
    dirs: list[tuple[float, str]],
) -> None:
    beacons = [_eq(f"b_{i}", kind, d) for i, (d, kind) in enumerate(dirs)]
    assert extract_theatres._navaids(beacons, "T") == {}


def _theatres() -> dict[str, dict[str, object]]:
    return {
        "Nevada": {"id": "Nevada", "directory": "Nevada", "displayName": "Nevada"},
        "GermanyCW": {"id": "GermanyCW", "directory": "GermanyColdWar"},
    }


def test_aliases_applied_and_stamped(capsys: pytest.CaptureFixture[str]) -> None:
    theatres = _theatres()
    extract_theatres.apply_aliases(
        theatres, {"Nevada": ["NTTR"], "Kola": ["Kola Peninsula"]}
    )
    assert theatres["Nevada"]["aliases"] == ["NTTR"]
    assert theatres["Nevada"]["_source"] == {"aliases": "hand-authored"}
    assert "aliases" not in theatres["GermanyCW"]
    assert "no theatre 'Kola'" in capsys.readouterr().err


@pytest.mark.parametrize(
    "table",
    [
        {"Nevada": [" nevada "]},
        {"GermanyCW": ["germanycoldwar"]},
        {"Nevada": ["Germany"], "GermanyCW": ["GERMANY"]},
        {"Nevada": "NTTR"},
    ],
)
def test_redundant_or_shared_aliases_fail(table: dict[str, object]) -> None:
    with pytest.raises(SystemExit):
        extract_theatres.apply_aliases(_theatres(), table)
