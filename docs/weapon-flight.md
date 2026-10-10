# Weapon flight data

`weapon_flight` has one record per weapon with the flight model, motor, autopilot, seeker and
fuze DCS configures for it, keyed like `weapons`. Values come from the `client` block of the
weapon's `weapons_table` record, or from its `_G/rockets`, `_G/bombs` or `_G/torpedoes` record
when it has no `weapons_table` one. They are DCS's inputs, not computed performance; the C++
code that uses them isn't visible. Keys with no field below are only in the [`_G`
dump](dcs-dump.md).

```ts
import { loadWeaponFlight } from 'dcs-world-reference';

const amraam = (await loadWeaponFlight())['AIM_120C'];
console.log(amraam?.batteryLifeS, amraam?.aerodynamics?.cx0);
```

28 missiles have no flight model in Lua (TOW, Kormoran and several SAM missiles); their records hold
only what the scripts give.

## WeaponFlight

| Field | DCS key | Unit |
| --- | --- | --- |
| `weapon` | | `Entity.Weapon` id |
| `batteryLifeS` | `Life_Time` | s |
| `killDistanceM` | `KillDistance` | m |
| `rangeMaxM` | `Range_max` (AI) | m |
| `machMax` | `Mach_max` | |
| `pnCoefficients` | `PN_coeffs` | `distanceM`, `gain` pairs |
| `launchEnvelopes` | `LaunchDistData`, `MinLaunchDistData`, `AspectDistData` | see below |
| `aerodynamics` | `fm` | |
| `motorStages` | `boost`, `march`, `march2`, `engine`, ... | |
| `autopilot` | `autopilot`, else `ap` | |
| `seeker` | `seeker`, else `sensor` | |
| `gimbal` | `gimbal` | |
| `proximityFuze` | `proximity_fuze` | |

## Aerodynamics

Coefficient tables are sampled by Mach from Mach 0 in steps of `machStep`; arrays are exactly as
DCS has them.

| Field | DCS key | Unit |
| --- | --- | --- |
| `massKg` | `mass` | kg |
| `caliberM` | `caliber` | m |
| `lengthM` | `L` | m |
| `referenceArea` | `S` | not stated |
| `machStep` | `table_scale` | Mach |
| `cx0` | `Cx0` | zero-lift drag |
| `cxB` | `CxB` | base drag |
| `k1`, `k2` | `K1`, `K2` | induced drag polar |
| `cya`, `cza` | `Cya`, `Cza` | lift / side-force slope |
| `mya`, `mza` | `Mya`, `Mza` | yaw / pitch moment slope |
| `myw`, `mzw` | `Myw`, `Mzw` | yaw / pitch damping |
| `a1Trim`, `a2Trim` | `A1trim`, `A2trim` | balancing AoA, pitch / yaw |
| `cxCoeff` | `cx_coeff` | bomb and rocket drag |
| `ix`, `iy`, `iz` | `Ix`, `Iy`, `Iz` | not stated |
| `finDeflectionMaxRad` | `delta_max` | rad |
| `maxAoaRad` | `maxAoa` | rad |

## Motor stages

One per stage block, sorted by key. Smoke-only blocks (the `march` of AGM-62, AGM-65 and RB 75)
are not stages.

| Field | DCS key | Unit |
| --- | --- | --- |
| `stage` | block key | |
| `impulseS` | `impulse` | s (specific impulse) |
| `fuelMassKg` | `fuel_mass` | kg |
| `workTimeS` | `work_time` | s |
| `boostFactor` | `boost_factor` | |
| `thrust` | torpedo `thrust`, else `default_thrust` | not stated |
| `startTime` | controller `<stage>_start` | not stated |

## Autopilot, seeker, gimbal, fuze

| Block | Field | DCS key | Unit |
| --- | --- | --- | --- |
| autopilot | `navigationGain` | `Knav` | |
| | `gLoadLimit` | `gload_limit` | g |
| | `finsLimitRad` | `fins_limit` | rad |
| | `operatingTime` | `op_time` | not stated |
| seeker | `fovRad` | `FOV` | rad (full or half angle not stated) |
| | `nearDistance`, `farDistance` | `sens_near_dist`, `sens_far_dist` | not stated |
| | `operatingTime` | `op_time` | not stated |
| gimbal | `yawMaxRad`, `pitchMaxRad` | `yaw_max`, `pitch_max` | rad |
| | `trackingRateMaxRadS` | `max_tracking_rate` | rad/s (`math.rad(n)` per second, the time unit implied) |
| | `operatingTime` | `op_time` | not stated |
| proximityFuze | `radius` | `radius` | not stated |
| | `armDelay` | `arm_delay` | not stated |

`batteryLifeS` and the blocks' `operatingTime` are separate limits; none of them is the others.

## Launch envelopes

`LaunchDistData`, `MinLaunchDistData` and `AspectDistData` are `{rows, cols, column headers,
then each row's header and cells}`. Rows are launch altitude in metres, columns launch true
airspeed in m/s. `launchEnvelopes` holds them as `altitudesM`, `speedsMs` and grids indexed
`[altitude][speed]`: `maxRangeM` and `minRangeM` in metres, `aspectDeg` in degrees, in DCS order.
Tables with the same axes share an envelope; a weapon whose tables have different axes gets one
envelope per axes pair. `RmaxData`, `LoftData`, `LaunchDistData2` and the like are only in the dump.

## Not typed

Only in the dump: `ModelData` (positional, meanings unknown), torpedo `data_table` and
`rail_thrust`, smoke keys, cluster submunition blocks under `launcher.cluster`, and the rest of
each block.
