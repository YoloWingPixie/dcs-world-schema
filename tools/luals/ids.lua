-- DcsId types: completions offer DCS's ids with their display names, and
-- `| string` keeps ids DCS adds through mods.
---@type DcsId.UnitType|string
local unitType = "$" --! complete "F-16C_50"
---@type DcsId.UnitType|string
local modded = "MyMod_F-16"
---@type DcsId.AircraftType
local typo = "F-16C" --! assign-type-mismatch
---@type DcsId.AircraftType
local $hornet = "FA-18C_hornet" --! hover F/A-18C
---@type DcsId.Theatre.Caucasus.AirdromeId
local anapa = 12
