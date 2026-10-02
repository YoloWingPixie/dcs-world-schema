from pathlib import Path
from typing import Any

import pytest
from conftest import write

from tools.datamine.extract_liveries import (
    build_liveries,
    map_countries,
    walk_liveries,
)

USA = {"id": 2, "idName": "USA", "name": "USA", "shortName": "USA"}
UK = {"id": 4, "idName": "UK", "name": "UK", "shortName": "UK"}


def _mock_install(root: Path) -> Path:
    install = root / "install"
    write(
        install / "CoreMods/aircraft/F-16C/Liveries/F-16C_50/Aggressor/description.lua",
        'name = "Aggressor Ferris"\ncountries = {"USA"}\nlivery = {}\n',
    )
    write(
        install
        / "CoreMods/aircraft/F-16C_2/Liveries/F-16C_50/Aggressor/description.lua",
        'countries = {"USA"}\n',
    )
    write(
        install / "Bazar/Liveries/A-10C/Standard/description.lua",
        'countries = {"USA", "XXX"}\n',
    )
    write(
        install / "Bazar/Liveries/A-10C/Fictional/description.lua",
        'countries = {"XXX", ""}\n',
    )
    write(install / "Bazar/Liveries/A-10C/Empty/description.lua", "countries = {}\n")
    write(install / "Bazar/Liveries/A-10C/Any/description.lua", 'name = "Any"\n')
    (install / "Bazar/Liveries/Ka-50/BareMetal").mkdir(parents=True)
    return install


def test_walk_tags_modules_and_paths(tmp_path: Path) -> None:
    walk = walk_liveries(_mock_install(tmp_path))

    assert sorted(walk.records) == [
        "Bazar/Liveries/A-10C/Any/description.lua",
        "Bazar/Liveries/A-10C/Empty/description.lua",
        "Bazar/Liveries/A-10C/Fictional/description.lua",
        "Bazar/Liveries/A-10C/Standard/description.lua",
        "Bazar/Liveries/Ka-50/BareMetal",
        "CoreMods/aircraft/F-16C/Liveries/F-16C_50/Aggressor/description.lua",
        "CoreMods/aircraft/F-16C_2/Liveries/F-16C_50/Aggressor/description.lua",
    ]
    core = walk.records[
        "CoreMods/aircraft/F-16C/Liveries/F-16C_50/Aggressor/description.lua"
    ]
    assert core["module"] == "aircraft/F-16C"
    assert core["name"] == "Aggressor Ferris"
    assert core["id"] == core["path"]

    bazar = walk.records["Bazar/Liveries/A-10C/Standard/description.lua"]
    assert "module" not in bazar
    assert bazar["name"] == "Standard"

    bare = walk.records["Bazar/Liveries/Ka-50/BareMetal"]
    assert "countries" not in bare
    assert bare["id"] == bare["path"] == "Bazar/Liveries/Ka-50/BareMetal"
    assert walk.failures == []


def test_description_runs_without_library_access(tmp_path: Path) -> None:
    install = tmp_path / "install"
    write(
        install / "Bazar/Liveries/Ka-50/Evil/description.lua",
        'os.execute("echo pwned")\nname = "x"\n',
    )
    write(install / "Bazar/Liveries/Ka-50/Loop/description.lua", "while true do end\n")
    walk = walk_liveries(install)
    assert len(walk.failures) == 2
    assert walk.records["Bazar/Liveries/Ka-50/Evil/description.lua"]["name"] == "Evil"


def _mapped(
    tmp_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    walk = walk_liveries(_mock_install(tmp_path))
    unmapped = map_countries(walk.records, [UK, USA])
    by_name: dict[str, dict[str, Any]] = {
        k.split("/")[-2] if k.endswith("description.lua") else k.split("/")[-1]: {
            f: r[f]
            for f in ("countries", "countryNames", "unmappedCountries")
            if f in r
        }
        for k, r in walk.records.items()
        if "/A-10C/" in k or "/Ka-50/" in k
    }
    return by_name, unmapped


def test_country_short_names_map_to_ids(tmp_path: Path) -> None:
    by_name, unmapped = _mapped(tmp_path)
    assert by_name == {
        # No countries table (or no description.lua): every country's.
        "Any": {},
        "BareMetal": {},
        # countries = {}: listed, naming none.
        "Empty": {"countries": [], "countryNames": []},
        # Some strings map.
        "Standard": {
            "countries": [2],
            "countryNames": ["USA"],
            "unmappedCountries": ["XXX"],
        },
        # No string maps: kept, raw and sorted.
        "Fictional": {
            "countries": [],
            "countryNames": [],
            "unmappedCountries": ["", "XXX"],
        },
    }
    assert unmapped == {
        "": {"Bazar/Liveries/A-10C/Fictional/description.lua"},
        "XXX": {
            "Bazar/Liveries/A-10C/Fictional/description.lua",
            "Bazar/Liveries/A-10C/Standard/description.lua",
        },
    }


def test_all_mapped_has_no_unmapped_field(tmp_path: Path) -> None:
    walk = walk_liveries(_mock_install(tmp_path))
    map_countries(walk.records, [USA])
    record = walk.records[
        "CoreMods/aircraft/F-16C/Liveries/F-16C_50/Aggressor/description.lua"
    ]
    assert record["countries"] == [2]
    assert record["countryNames"] == ["USA"]
    assert "unmappedCountries" not in record


def test_short_names_match_exactly(tmp_path: Path) -> None:
    install = tmp_path / "install"
    write(install / "Bazar/Liveries/A-10C/x/description.lua", 'countries = {"usa"}\n')
    walk = walk_liveries(install)
    assert map_countries(walk.records, [USA]) == {
        "usa": {"Bazar/Liveries/A-10C/x/description.lua"}
    }


def test_non_string_country_fails(tmp_path: Path) -> None:
    install = tmp_path / "install"
    write(
        install / "Bazar/Liveries/A-10C/x/description.lua", 'countries = {"USA", 2}\n'
    )
    with pytest.raises(SystemExit):
        walk_liveries(install)


def test_unexplained_unmapped_country_fails(tmp_path: Path) -> None:
    install = _mock_install(tmp_path)
    with pytest.raises(SystemExit):
        build_liveries(install, [USA], {}, {"XXX": "placeholder"})


def test_explained_unmapped_countries_pass(tmp_path: Path) -> None:
    install = _mock_install(tmp_path)
    records, problems = build_liveries(
        install, [USA], {}, {"XXX": "placeholder", "": "empty string"}
    )
    assert records["Bazar/Liveries/A-10C/Standard/description.lua"][
        "unmappedCountries"
    ] == ["XXX"]
    assert not any("country" in p for p in problems)


@pytest.mark.parametrize("stale", ["GONE", "USA"])
def test_stale_gap_entry_fails(tmp_path: Path, stale: str) -> None:
    install = _mock_install(tmp_path)
    gaps = {"XXX": "placeholder", "": "empty string", stale: "stale"}
    with pytest.raises(SystemExit):
        build_liveries(install, [USA], {}, gaps)


def test_absent_roots_yield_nothing(tmp_path: Path) -> None:
    assert walk_liveries(tmp_path / "nope").records == {}


def test_unit_types_by_entry_point(tmp_path: Path) -> None:
    install = tmp_path / "install"
    for folder in ("p-51d", "RLS_19J6", "F_A-18X", "gbu-54"):
        (install / "Bazar/Liveries" / folder / "default").mkdir(parents=True)
    units = {
        "P-51D": {"livery_entry": "P-51D"},
        "P-51D-30-NA": {"livery_entry": "P-51D"},
        "rls_19j6": {},
        "F/A-18X": {},
    }
    records, _ = build_liveries(install, [], units, {})
    assert {r["entryPoint"]: r["unitTypes"] for r in records.values()} == {
        "p-51d": ["P-51D", "P-51D-30-NA"],
        "RLS_19J6": ["rls_19j6"],
        "F_A-18X": ["F/A-18X"],
        "gbu-54": [],
    }
