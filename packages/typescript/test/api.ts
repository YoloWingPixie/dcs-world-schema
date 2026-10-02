import {
  bestRunway,
  countryId,
  countryName,
  datalinkCapability,
  destination,
  distanceBearing,
  formatCoord,
  isValidTacan,
  launchPlatforms,
  liveriesFor,
  modelToUnits,
  navaidsFor,
  nearestAirbases,
  parseCoord,
  runwayEnds,
  standsFor,
  tacanChannel,
  tacanFrequency,
  unitDetection,
  weaponInfo,
  FREQUENCY_TOLERANCE_MHZ,
  NM_M,
  WIND_TOLERANCE_KT,
  type BestRunway,
  type CoordFormat,
  type DatalinkCapability,
  type DistanceBearing,
  type LaunchPlatforms,
  type NearbyAirbase,
  type ParsedCoord,
  type RunwayEnd,
  type RunwayThreshold,
  type SensorSummary,
  type TacanBand,
  type TacanChannel,
  type TacanFrequency,
  type UnitDetectionInfo,
  type WarheadInfo,
  type WeaponInfo,
  aircraftCarrying,
  aircraftRoles,
  canMount,
  fitStores,
  isValidFrequency,
  loadoutMass,
  radioBands,
  stationsAccepting,
  theatreByName,
  threatForUnitType,
  threatRange,
  threatRingGeoJSON,
  toLatLon,
  toMapXZ,
  unitClass,
  type FitResult,
  type FrequencyCheck,
  type LatLon,
  type LoadoutMass,
  type MapXZ,
  type RadioBands,
  type Theatre,
  type ThreatRange,
  type ThreatRingCollection,
  airbaseByName,
  BeaconType,
  dcsVersion,
  findByName,
  loadAircraft,
  loadIndexMeta,
  loadManifest,
  loadSeries,
  nameKey,
  referencesTo,
  seriesNames,
  storesDelivering,
  threatsForUnit,
  type Aircraft,
  type Beacon,
  type IndexMeta,
  type Provenance,
  type Reference,
  type Series,
  type SeriesName,
} from 'dcs-world-reference';
import { aircraft } from 'dcs-world-reference/aircraft';
import beacons from 'dcs-world-reference/beacons';

export const version: string = dcsVersion;
export const eager: Series<Aircraft> = aircraft;
export const eagerDefault: Series<Beacon> = beacons;
export const lazy: Promise<Series<Aircraft>> = loadAircraft();
export const generic: Promise<Series<Beacon>> = loadSeries('beacons');
export const manifest: Promise<Provenance> = loadManifest();
export const names: readonly SeriesName[] = seriesNames;
export const tacan: BeaconType = BeaconType.BEACON_TYPE_TACAN;

export const refs: Promise<readonly Reference[]> = referencesTo('weapons', 'AIM_120C');
export const carriers: Promise<readonly string[]> = aircraftCarrying('AIM_120C');
export const delivering: Promise<readonly string[]> = storesDelivering('AIM_120C');
export const threats: Promise<readonly string[]> = threatsForUnit('SA-11 Buk LN 9A310M1');
export const batumi: Promise<readonly string[]> = airbaseByName('Batumi', 'Caucasus');
export const viper: Promise<readonly string[]> = findByName('aircraft', 'F-16CM bl.50');
export const meta: Promise<IndexMeta> = loadIndexMeta();
export const key: string = nameKey(' F-16C ');
export const nttr: Promise<Theatre | undefined> = theatreByName('NTTR');
export const geo: Promise<LatLon> = toLatLon('Caucasus', 0, 0);
export const map: Promise<MapXZ> = toMapXZ('Caucasus', 42, 41);
export const sa10: Promise<ThreatRange> = threatRange('SA5B55');
export const sa10Units: Promise<readonly string[]> = threatForUnitType('S-300PS 5P85C ln');
export const ring: Promise<ThreatRingCollection> = threatRingGeoJSON('SA5B55', 42, 41, { segments: 16 });
export const roles: Promise<readonly string[]> = aircraftRoles('KC-135');
export const unitKind: Promise<string> = unitClass('Hawk ln');
export const accepting: Promise<readonly number[]> = stationsAccepting('F-16C_50', 'CATM-9M');
export const mountable: Promise<boolean> = canMount('F-16C_50', 1, 'CATM-9M');
export const fit: Promise<FitResult> = fitStores('F-16C_50', ['CATM-9M']);
export const mass: Promise<LoadoutMass> = loadoutMass('F-16C_50', { 1: 'CATM-9M' }, 1000);
export const bands: Promise<readonly RadioBands[]> = radioBands('F-16C_50');
export const tuned: Promise<FrequencyCheck> = isValidFrequency('F-16C_50', 0, 251);
export const amraam: Promise<WeaponInfo> = weaponInfo('AIM_120C');
export const amraamWarhead = async (): Promise<WarheadInfo | undefined> => (await amraam).warhead;
export const platforms: Promise<LaunchPlatforms> = launchPlatforms('AIM_120C');
export const viperModels: Promise<readonly string[]> = modelToUnits('f-16');
export const detection: Promise<UnitDetectionInfo> = unitDetection('SA-11 Buk SR 9S18M1');
export const firstSensor = async (): Promise<SensorSummary | undefined> => (await detection).sensors[0];
export const band: TacanBand = 'X';
export const tacanTx: Promise<TacanFrequency> = tacanFrequency(16, band, 'ground');
export const tacanRx: Promise<readonly TacanChannel[]> = tacanChannel(977, 'ground');
export const tacanOk: Promise<boolean> = isValidTacan(16, 'Y');
export const ils: Promise<readonly string[]> = navaidsFor('Caucasus.22', '13');
export const ends: Promise<readonly RunwayEnd[]> = runwayEnds('Caucasus.22');
export const threshold = async (): Promise<RunwayThreshold | undefined> => (await ends)[0]?.threshold;
export const active: Promise<BestRunway> = bestRunway('Caucasus.22', 300, 12);
export const near: Promise<readonly NearbyAirbase[]> = nearestAirbases('Caucasus', 41.6, 41.6, { n: 3, minRunwayM: 2000 });
export const stands: Promise<readonly number[]> = standsFor('Caucasus.25', 'C-130J-30');
export const nz: Promise<number | undefined> = countryId('New Zealand');
export const usa: Promise<string> = countryName(2);
export const skins: Promise<readonly string[]> = liveriesFor('F-16C_50', 2);
export const link16: Promise<DatalinkCapability | undefined> = datalinkCapability('F-16C_50');
export const leg: DistanceBearing = distanceBearing(41.6, 41.6, 42, 42);
export const there: LatLon = destination(41.6, 41.6, 45, 10000);
export const fmt: CoordFormat = 'MGRS';
export const grid: string = formatCoord(0, 0, fmt, 5);
export const parsed: ParsedCoord = parseCoord('MGRS GRID: 39 R XN 54929 68251');
export const tolerances: number = FREQUENCY_TOLERANCE_MHZ + WIND_TOLERANCE_KT + NM_M;
// @ts-expect-error not a coordinate format
formatCoord(0, 0, 'UTM');
// @ts-expect-error not a TACAN band
void tacanFrequency(16, 'Z', 'air');
export const firstSeries =async (): Promise<SeriesName | undefined> => (await refs)[0]?.series;

// @ts-expect-error not a series
void loadSeries('nope');
// @ts-expect-error series maps are read-only
aircraft['x'] = eager['y']!;
// @ts-expect-error not a series
void referencesTo('nope', 'x');
// @ts-expect-error not a series
void findByName('nope', 'x');
