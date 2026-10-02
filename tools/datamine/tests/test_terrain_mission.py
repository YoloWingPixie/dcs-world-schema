"""The per-terrain empty mission: install defaults, Lua text, deterministic zip."""

import zipfile
from pathlib import Path
from typing import Any

import pytest
from conftest import write

from tools.datamine import actions_probe, probe_mission, terrain_mission
from tools.datamine.common import load_series
from tools.datamine.lua_reader import lua_to_py, sandbox_exec


def _install(root: Path, stamp: str = "20260902-093323") -> Path:
    write(root / "autoupdate.cfg", f'{{"version": "2.9.99.1", "timestamp": "{stamp}"}}')
    write(
        root / terrain_mission.ME_MISSION,
        "local base = _G\nlocal VERSION_MISSION = 23\n",
    )
    write(
        root / terrain_mission.DEFAULT_WEATHER,
        'vdata = { qnh = 760, name = "Winter, clean sky", clouds = { base = 2520 } }\n',
    )
    write(
        root / terrain_mission.DEFAULT_COALITIONS,
        "coalitions = { blue = { 1, 11, -- US\n 4 }, red = { 0, 18 } }\n",
    )
    return root


def _load(text: str, name: str) -> Any:
    ok, env = sandbox_exec(text, name)
    assert ok, env
    return lua_to_py(env[name])


def test_mission_from_install_defaults(tmp_path: Path) -> None:
    defaults = terrain_mission.install_defaults(_install(tmp_path))
    files = terrain_mission.mission_files("Caucasus", defaults)
    assert list(files) == [
        "mission",
        "warehouses",
        "theatre",
        "l10n/DEFAULT/dictionary",
        "l10n/DEFAULT/mapResource",
    ]
    assert files["theatre"] == "Caucasus"
    m = _load(files["mission"], "mission")
    assert m["theatre"] == "Caucasus"
    assert m["version"] == 23
    assert m["date"] == {"Year": 2026, "Month": 1, "Day": 1}
    assert m["start_time"] == 28800
    assert m["weather"]["clouds"]["base"] == 2520
    assert m["coalitions"] == {"blue": [1, 11, 4], "red": [0, 18], "neutrals": {}}
    assert m["coalition"]["red"]["name"] == "red"
    dictionary = _load(files["l10n/DEFAULT/dictionary"], "dictionary")
    assert dictionary[m["sortie"]] == ""
    assert m["maxDictId"] == len(dictionary)
    assert _load(files["warehouses"], "warehouses") == {
        "airports": {},
        "warehouses": {},
    }


def test_miz_is_deterministic(tmp_path: Path) -> None:
    files = terrain_mission.mission_files(
        "Normandy", terrain_mission.install_defaults(_install(tmp_path / "dcs"))
    )
    a, b = tmp_path / "a.miz", tmp_path / "b.miz"
    terrain_mission.write_miz(a, files)
    terrain_mission.write_miz(b, files)
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as z:
        assert z.namelist() == list(files)
        assert z.read("theatre") == b"Normandy"


def test_lua_literal_escapes_and_orders() -> None:
    text = terrain_mission.lua_literal({"b": [1, 2.5], "a": 'q"\n', 3: True})
    assert _load("x = " + text, "x") == {"3": True, "a": 'q"\n', "b": [1, 2.5]}
    assert text.index("[3]") < text.index('["a"]') < text.index('["b"]')


@pytest.mark.parametrize("stamp", ["", "2026-09-02", "x"])
def test_build_year_needs_timestamp(tmp_path: Path, stamp: str) -> None:
    with pytest.raises(SystemExit):
        terrain_mission.build_year(_install(tmp_path, stamp))


def test_missing_version_mission_fails(tmp_path: Path) -> None:
    root = _install(tmp_path)
    write(root / terrain_mission.ME_MISSION, "-- nothing\n")
    with pytest.raises(SystemExit):
        terrain_mission.install_defaults(root)


def test_real_install_mission(tmp_path: Path) -> None:
    import os

    install = Path(os.environ.get("DCS_INSTALL_DIR", "/mnt/d/DCS World OpenBeta"))
    if not (install / terrain_mission.ME_MISSION).is_file():
        pytest.skip("no DCS install")
    defaults = terrain_mission.install_defaults(install)
    m = _load(terrain_mission.mission_files("Caucasus", defaults)["mission"], "mission")
    assert m["version"] >= 23 and m["weather"]["qnh"] == 760


PROBE_DEFAULTS = {
    "version": 23,
    "weather": {"qnh": 760},
    "coalitions": {"blue": [2], "red": [0], "neutrals": []},
    "year": 2026,
}


def test_probe_mission_contents() -> None:
    spec = probe_mission.spec()
    mission = probe_mission.build(spec, PROBE_DEFAULTS)
    assert mission.id == probe_mission.build(spec, PROBE_DEFAULTS).id
    m = _load(mission.files["mission"], "mission")
    assert m["theatre"] == "Caucasus"
    blue = m["coalition"]["blue"]["country"][0]
    red = m["coalition"]["red"]["country"][0]
    assert (blue["id"], red["id"]) == (2, 0)
    planes = {g["name"]: g for g in blue["plane"]["group"]}
    assert set(planes) == {"PROBE_PLANE_BLUE", "PROBE_CLIENT_BLUE"}
    plane = planes["PROBE_PLANE_BLUE"]
    assert plane["units"][0]["name"] == "PROBE_PLANE_BLUE-1"
    assert plane["units"][0]["callsign"]["name"] == "Enfield11"
    tasks = [t["id"] for t in plane["route"]["points"][0]["task"]["params"]["tasks"]]
    assert tasks == ["WrappedAction", "WrappedAction", "WrappedAction", "Orbit"]
    assert planes["PROBE_CLIENT_BLUE"]["units"][0]["skill"] == "Client"
    assert red["plane"]["group"][0]["units"][0]["callsign"] == 101
    vehicles = {g["name"]: g for g in red["vehicle"]["group"]}
    assert set(vehicles) == {"PROBE_GROUND_RED", "PROBE_SAM_RED", "PROBE_ARTY_RED"}
    arty = vehicles["PROBE_ARTY_RED"]["route"]["points"][0]["task"]["params"]
    assert arty["tasks"] == {}  # the mortar does not hold fire
    ships = [g["units"][0]["type"] for g in blue["ship"]["group"]]
    assert ships == ["PERRY", "Stennis"]
    statics = {g["name"]: g["units"][0] for g in blue["static"]["group"]}
    assert statics["PROBE_FARP_BLUE"]["category"] == "Heliports"
    assert statics["PROBE_CARGO_BLUE"]["canCargo"] is True
    ids = [
        g["groupId"]
        for side in (blue, red)
        for cat in ("plane", "helicopter", "vehicle", "ship", "static")
        for g in side[cat]["group"]
    ]
    assert sorted(ids) == list(range(1, len(ids) + 1))
    zones = {z["name"]: z for z in m["triggers"]["zones"]}
    assert zones["PROBE_ZONE_C"]["type"] == 0
    assert (
        zones["PROBE_ZONE_Q"]["type"] == 2
        and len(zones["PROBE_ZONE_Q"]["verticies"]) == 4
    )
    common = [layer for layer in m["drawings"]["layers"] if layer["name"] == "Common"]
    assert common[0]["objects"][0]["name"] == "PROBE_DRAWING"
    assert m["trigrules"][0]["predicate"] == "triggerStart"
    action = m["trig"]["actions"][0]
    assert (
        action.startswith("a_do_script(") and 'markToAll(1, \\"PROBE_MARK\\"' in action
    )
    assert 'setUserFlag(\\"PROBE_FLAG\\", 1)' in action
    warehouses = _load(mission.files["warehouses"], "warehouses")
    kutaisi = warehouses["airports"]["25"]
    assert kutaisi["coalition"] == "BLUE" and kutaisi["unlimitedMunitions"] is False
    assert kutaisi["aircrafts"]["planes"]["F-15C"]["initialAmount"] == 4
    assert mission.pools["groups"][0] == "PROBE_PLANE_BLUE"
    assert mission.pools["zones"] == ["PROBE_ZONE_C", "PROBE_ZONE_Q"]
    assert "PROBE_FARP_BLUE" in mission.pools["airbases"]
    assert mission.pools["sides"] == [2, 1]
    assert mission.samples["arty"] == "PROBE_ARTY_BLUE"


def test_probe_mission_followup_objects() -> None:
    spec = actions_probe.followup_mission_spec(
        probe_mission.spec(), actions_probe.followup_spec()
    )
    m = _load(probe_mission.build(spec, PROBE_DEFAULTS).files["mission"], "mission")
    blue = m["coalition"]["blue"]["country"][0]
    red = m["coalition"]["red"]["country"][0]
    bomber = next(g for g in blue["plane"]["group"] if g["name"] == "PROBE_BOMBER_BLUE")
    assert bomber["units"][0]["payload"]["pylons"]["4"] == {"CLSID": "{Mk82AIR}"}
    first = bomber["route"]["points"][0]["task"]["params"]["tasks"]
    assert first[0]["params"]["action"]["params"] == {"name": 0, "value": 2}
    assert not [g for g in red["plane"]["group"] if g["name"] == "PROBE_BOMBER_RED"]
    target = next(g for g in red["vehicle"]["group"] if g["name"] == "PROBE_TARGET_RED")
    x, y = spec["sides"]["blue"]["land"]
    assert (target["x"], target["y"]) == (x - 2000, y - 23000)
    actions = [
        t["params"]["action"]["id"]
        for t in target["route"]["points"][0]["task"]["params"]["tasks"]
    ]
    assert actions == ["Option", "SetImmortal"]


def test_probe_mission_values_from_dcs_data() -> None:
    s = probe_mission.spec()
    aircraft = load_series(probe_mission.reference_dir(), "aircraft")
    plane = next(o for o in s["objects"] if o["name"] == "PROBE_PLANE")
    for side, type_ in plane["type"].items():
        rec = next(r for r in aircraft.values() if r["id"] == type_)
        assert plane["fuel"][side] == rec["aero"]["internalFuelKg"]
        assert plane["speed"][side] == rec["performance"]["vOptMs"]
    hold = s["roe"]["Ground"]["hold"]["params"]["action"]
    assert hold == {"id": "Option", "params": {"name": 0, "value": 4}}


def test_aircraft_value_words_need_aircraft_data() -> None:
    helo = {
        "name": "H",
        "kind": "helicopter",
        "type": "UH-60A",
        "fuel": "internal",
        "speed": "optimal",
    }
    with pytest.raises(SystemExit):  # rotary types have no vOptMs
        probe_mission.resolve_objects([helo], "test")
    with pytest.raises(SystemExit):  # an aircraft needs a speed
        probe_mission.resolve_objects([{**helo, "speed": None}], "test")
    with pytest.raises(SystemExit):  # words are for aircraft only
        probe_mission.resolve_objects(
            [{"name": "V", "kind": "vehicle", "type": "T-72B", "fuel": "internal"}],
            "test",
        )


def test_probe_mission_needs_the_countries_in_their_coalitions() -> None:
    defaults = {
        **PROBE_DEFAULTS,
        "coalitions": {"blue": [1], "red": [0], "neutrals": []},
    }
    with pytest.raises(SystemExit):
        probe_mission.build(probe_mission.spec(), defaults)


def test_probe_mission_pools_without_install() -> None:
    mission = probe_mission.build(probe_mission.spec(), None)
    assert mission.files == {}
    assert mission.pools["statics"][0] == "PROBE_STATIC_BLUE"
