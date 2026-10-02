"""Flyable declarations from the install's plugin entry.lua files."""

from pathlib import Path
from typing import Any

import pytest
from conftest import write

from tools.datamine.extract_flyables import (
    check_coverage,
    declared_flyables,
    declared_in,
    flyable_types,
    missing_units,
)

# The call shapes found in the 2.9.29 install's Mods/aircraft/*/entry.lua.
_ENTRY = """
local self_ID = "F-14 by Heatblur"
local flyable_ID = "AH-64D_BLK_II"
declare_plugin(self_ID, {displayName = _("F-14"), version = __DCS_VERSION__,
    InputProfiles = {[flyable_ID .. "_PLT"] = current_mod_path .. '/Input/'}})
mount_vfs_texture_path(current_mod_path .. "/Textures")
dofile(current_mod_path .. "/Views.lua")
local cfg_path = current_mod_path .. "/FM/config.lua"
dofile(cfg_path)
FM[1] = self_ID
FM.config_path = cfg_path
FM.mass = FM.mass * 2 + 1
make_view_settings('F-14B', ViewSettings, SnapViews)
make_flyable('F-14B',current_mod_path..'/Cockpit/',FM,current_mod_path..'/comm.lua')--make_flyable(obj_name,cockpit)
MAC_flyable('Su-25' , current_mod_path..'/Cockpit/KneeboardRight/', nil, current_mod_path..'/Comm/Su-25.lua')
make_flyable("F-15ESE", current_mod_path..'/Cockpit/',F15EFM,current_mod_path..'/comm.lua') -- EFM ON
make_flyable(flyable_ID, current_mod_path..'/Cockpit/Scripts/', AH64D, current_mod_path..'/comm.lua')
make_flyable(
    'P-51D-30-NA',
    current_mod_path .. '/Cockpit/Scripts/',
    {self_ID, 'P51B'},
    current_mod_path .. '/comm.lua'
) -- make_flyable(obj_name,optional_cockpit path)
-- make_flyable('Commented-Out', nil, nil, nil)
--[[ make_flyable('Block-Commented', nil, nil, nil) ]]
plugin_done()
"""


def test_declared_in_reads_every_call_variant() -> None:
    assert declared_in(_ENTRY, "entry.lua", "C:/DCS/Mods/aircraft/X") == [
        "F-14B",
        "Su-25",
        "F-15ESE",
        "AH-64D_BLK_II",
        "P-51D-30-NA",
    ]


def test_declared_in_rejects_non_string_id() -> None:
    with pytest.raises(ValueError, match="not a string"):
        declared_in("make_flyable(unknown_global, nil)", "entry.lua", "x")


def test_declared_flyables_scans_plugin_dirs(tmp_path: Path) -> None:
    write(tmp_path / "Mods/aircraft/F14/entry.lua", "make_flyable('F-14B', p)")
    write(tmp_path / "Mods/tech/Pack/entry.lua", "MAC_flyable('Su-33', p)")
    write(tmp_path / "CoreMods/aircraft/F14/entry.lua", "declare_plugin('AI', {})")
    assert declared_flyables(tmp_path) == {
        "F-14B": "Mods/aircraft/F14",
        "Su-33": "Mods/tech/Pack",
    }


def test_unreadable_entry_fails(tmp_path: Path) -> None:
    write(tmp_path / "Mods/aircraft/Bad/entry.lua", "make_flyable('X', (")
    with pytest.raises(SystemExit):
        declared_flyables(tmp_path)


def test_flyable_is_marker_or_declaration() -> None:
    units = {
        "Su-25T": {"_file_flyable": "x"},
        "F-16C_50": {},
        "B-52H": {},
    }
    assert flyable_types(units, {"F-16C_50": "Mods/aircraft/F-16C"}) == {
        "Su-25T",
        "F-16C_50",
    }


def test_coverage_fails_on_declared_id_without_unit() -> None:
    declared = {"F-16C_50": "Mods/aircraft/F-16C", "F-99": "Mods/aircraft/F-99"}
    units: dict[str, dict[str, Any]] = {"F-16C_50": {}}
    assert missing_units(declared, units) == ["F-99 (Mods/aircraft/F-99)"]
    with pytest.raises(SystemExit):
        check_coverage(declared, units)
    check_coverage({"F-16C_50": "Mods/aircraft/F-16C"}, units)
