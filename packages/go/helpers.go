package dcsref

// Reference helpers: pure functions of the embedded data (map projection,
// threat rings, unit classification, loadout fit and mass, radio tuning,
// weapons and detection, TACAN channels, runways and stands, countries,
// liveries and datalinks; the geo maths is in geo.go).
// They implement the Python package's helpers (the reference) and are held to
// its results by the shared conformance vectors. Unknown ids return an error
// wrapping ErrNotFound; impossible inputs one wrapping ErrInvalid.

import (
	"errors"
	"fmt"
	"math"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
)

var (
	// ErrNotFound is wrapped by the errors of helpers given an id the data
	// does not hold.
	ErrNotFound = errors.New("dcsref: not found")
	// ErrInvalid is wrapped by the errors of helpers given an input they
	// cannot answer for.
	ErrInvalid = errors.New("dcsref: invalid input")
)

func notFound(format string, a ...any) error {
	return fmt.Errorf("%w: "+format, append([]any{ErrNotFound}, a...)...)
}

func invalid(format string, a ...any) error {
	return fmt.Errorf("%w: "+format, append([]any{ErrInvalid}, a...)...)
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	return keys
}

// Theatre projection --------------------------------------------------------

// LatLon is a WGS84 latitude/longitude in degrees.
type LatLon struct {
	Lat float64 `json:"lat"`
	Lon float64 `json:"lon"`
}

// MapXZ is a DCS map position in metres: X north, Z east.
type MapXZ struct {
	X float64 `json:"x"`
	Z float64 `json:"z"`
}

// WGS84 and the Krueger series to order n^6 (Karney 2011), as
// tools/datamine/tmerc.py fitted the projections with.
var (
	tmN     = tmF / (2 - tmF)
	tmE     = math.Sqrt(tmF * (2 - tmF))
	tmARect = tmA / (1 + tmN) * (1 + tmN*tmN/4 + math.Pow(tmN, 4)/64 + math.Pow(tmN, 6)/256)
	tmAlpha = krueger(tmN)
)

const (
	tmA      = 6378137.0
	tmF      = 1 / 298.257223563
	degToRad = math.Pi / 180
	radToDeg = 180 / math.Pi
)

func krueger(n float64) [6]float64 {
	p := func(k int) float64 { return math.Pow(n, float64(k)) }
	return [6]float64{
		n/2 - 2.0/3*p(2) + 5.0/16*p(3) + 41.0/180*p(4) - 127.0/288*p(5) + 7891.0/37800*p(6),
		13.0/48*p(2) - 3.0/5*p(3) + 557.0/1440*p(4) + 281.0/630*p(5) - 1983433.0/1935360*p(6),
		61.0/240*p(3) - 103.0/140*p(4) + 15061.0/26880*p(5) + 167603.0/181440*p(6),
		49561.0/161280*p(4) - 179.0/168*p(5) + 6601661.0/7257600*p(6),
		34729.0/80640*p(5) - 3418889.0/1995840*p(6),
		212378941.0 / 319334400 * p(6),
	}
}

// tm is (E, N) metres at unit scale, latitude of origin 0.
func tm(lat, dlon float64) (float64, float64) {
	phi, lam := lat*degToRad, dlon*degToRad
	s := math.Sin(phi)
	t := math.Sinh(math.Atanh(s) - tmE*math.Atanh(tmE*s))
	xiP := math.Atan2(t, math.Cos(lam))
	etaP := math.Atanh(math.Sin(lam) / math.Sqrt(1+t*t))
	xi, eta := xiP, etaP
	for i, a := range tmAlpha {
		j := float64(2 * (i + 1))
		xi += a * math.Sin(j*xiP) * math.Cosh(j*etaP)
		eta += a * math.Cos(j*xiP) * math.Sinh(j*etaP)
	}
	return tmARect * eta, tmARect * xi
}

func toMap(p *MapProjection, lat, lon float64) (float64, float64) {
	e, n := tm(lat, lon-p.CentralMeridian)
	k := p.ScaleFactor
	return p.FalseNorthing + k*n, p.FalseEasting + k*e
}

func projection(theatre string) (*MapProjection, error) {
	t, ok := TheatreByName(theatre)
	if !ok {
		return nil, notFound("no theatre %q", theatre)
	}
	if t.Projection == nil {
		return nil, invalid("theatre %s has no map projection", t.ID)
	}
	return t.Projection, nil
}

// TheatreByName returns the theatre whose id, displayName, directory or one
// of its aliases is name (trimmed, ASCII case-insensitive).
func TheatreByName(name string) (Theatre, bool) {
	key := NameKey(name)
	theatres := LoadTheatres()
	for _, id := range sortedKeys(theatres) {
		t := theatres[id]
		if NameKey(t.ID) == key || NameKey(t.Directory) == key ||
			(t.DisplayName != nil && NameKey(*t.DisplayName) == key) {
			return t, true
		}
		for _, a := range t.Aliases {
			if NameKey(a) == key {
				return t, true
			}
		}
	}
	return Theatre{}, false
}

// ToMapXZ returns the DCS map metres of a WGS84 latitude/longitude on theatre
// (anything TheatreByName accepts), through its Transverse Mercator
// projection.
func ToMapXZ(theatre string, lat, lon float64) (MapXZ, error) {
	p, err := projection(theatre)
	if err != nil {
		return MapXZ{}, err
	}
	x, z := toMap(p, lat, lon)
	return MapXZ{X: x, Z: z}, nil
}

// ToLatLon returns the WGS84 latitude/longitude of map metres (x, z) on
// theatre: Newton iteration on ToMapXZ from (0, central meridian) until both
// residuals are under a micrometre (at most 50 steps).
func ToLatLon(theatre string, x, z float64) (LatLon, error) {
	p, err := projection(theatre)
	if err != nil {
		return LatLon{}, err
	}
	return inverse(p, x, z)
}

// inverse is the latitude/longitude of map metres (x, z) under projection p.
func inverse(p *MapProjection, x, z float64) (LatLon, error) {
	lat, lon := 0.0, p.CentralMeridian
	const h = 1e-6
	for range 50 {
		px, pz := toMap(p, lat, lon)
		dx, dz := x-px, z-pz
		if math.Abs(dx) < 1e-6 && math.Abs(dz) < 1e-6 {
			return LatLon{Lat: lat, Lon: lon}, nil
		}
		x1, z1 := toMap(p, lat+h, lon)
		x2, z2 := toMap(p, lat, lon+h)
		a, b := (x1-px)/h, (x2-px)/h
		c, d := (z1-pz)/h, (z2-pz)/h
		det := a*d - b*c
		lat += (d*dx - b*dz) / det
		lon += (a*dz - c*dx) / det
	}
	return LatLon{}, invalid("ToLatLon did not converge for (%v, %v)", x, z)
}

// Threats ---------------------------------------------------------------------

// ThreatLimits is the union of a threat's engagement envelopes and its
// sensors' reach. A limit is set only when every envelope gives it.
type ThreatLimits struct {
	RMinKm      *float64 `json:"rMinKm,omitempty"`
	RMaxKm      *float64 `json:"rMaxKm,omitempty"`
	HMinM       *float64 `json:"hMinM,omitempty"`
	HMaxM       *float64 `json:"hMaxM,omitempty"`
	DetectionKm *float64 `json:"detectionKm,omitempty"`
}

// ThreatRange returns, over every component envelope and gunEnvelope of
// threat threatID: RMaxKm/HMaxM the largest, RMinKm/HMinM the smallest, each
// only when every envelope gives it (no envelopes: none). DetectionKm is the
// largest detectionRangeKm of its sensors (nil when none gives one).
func ThreatRange(threatID string) (ThreatLimits, error) {
	threat, ok := LoadThreats()[threatID]
	if !ok {
		return ThreatLimits{}, notFound("no threats record %q", threatID)
	}
	var envelopes []*ThreatEnvelope
	for _, c := range threat.Components {
		for _, e := range []*ThreatEnvelope{c.Envelope, c.GunEnvelope} {
			if e != nil {
				envelopes = append(envelopes, e)
			}
		}
	}
	pick := func(get func(*ThreatEnvelope) *float64, better func(a, b float64) bool) *float64 {
		if len(envelopes) == 0 {
			return nil
		}
		var out *float64
		for _, e := range envelopes {
			v := get(e)
			if v == nil {
				return nil
			}
			if out == nil || better(*v, *out) {
				out = new(float64)
				*out = *v
			}
		}
		return out
	}
	less := func(a, b float64) bool { return a < b }
	more := func(a, b float64) bool { return a > b }
	out := ThreatLimits{
		RMinKm: pick(func(e *ThreatEnvelope) *float64 { return e.RMinKm }, less),
		RMaxKm: pick(func(e *ThreatEnvelope) *float64 { return &e.RMaxKm }, more),
		HMinM:  pick(func(e *ThreatEnvelope) *float64 { return e.HMinM }, less),
		HMaxM:  pick(func(e *ThreatEnvelope) *float64 { return e.HMaxM }, more),
	}
	sensors := LoadSensors()
	for _, id := range threat.Sensors {
		if s, ok := sensors[id]; ok && s.DetectionRangeKm != nil {
			if out.DetectionKm == nil || *s.DetectionRangeKm > *out.DetectionKm {
				v := *s.DetectionRangeKm
				out.DetectionKm = &v
			}
		}
	}
	return out, nil
}

// unitView is what the helpers read of a unit record of any unit series.
type unitView struct {
	series    SeriesName
	attrs     []string
	kind      []string
	sensors   []string
	detection *UnitDetection
	model     *UnitModel
}

// unitOf returns unit type id from the first unit series holding it.
func unitOf(id string) (unitView, bool) {
	for _, s := range meta().UnitSeries {
		if v, ok := unitsOf(s)[id]; ok {
			return v, true
		}
	}
	return unitView{}, false
}

var (
	unitViewsMu sync.Mutex
	unitViews   = map[SeriesName]map[string]unitView{}
)

// unitsOf returns every unit of unit series s by id.
func unitsOf(s SeriesName) map[string]unitView {
	unitViewsMu.Lock()
	defer unitViewsMu.Unlock()
	if out, ok := unitViews[s]; ok {
		return out
	}
	out := map[string]unitView{}
	switch s {
	case SeriesAircraft:
		for id, u := range LoadAircraft() {
			out[id] = unitView{s, u.Attributes, []string{string(u.Kind)}, u.Sensors, u.Detection, u.Model}
		}
	case SeriesGroundVehicles:
		for id, u := range LoadGroundVehicles() {
			out[id] = unitView{s, u.Attributes, nil, u.Sensors, u.Detection, u.Model}
		}
	case SeriesPersonnel:
		for id, u := range LoadPersonnel() {
			out[id] = unitView{s, u.Attributes, nil, u.Sensors, nil, u.Model}
		}
	case SeriesShips:
		for id, u := range LoadShips() {
			out[id] = unitView{s, u.Attributes, nil, u.Sensors, u.Detection, u.Model}
		}
	case SeriesStructures:
		for id, u := range LoadStructures() {
			out[id] = unitView{s, u.Attributes, nil, u.Sensors, nil, u.Model}
		}
	default:
		panic(fmt.Sprintf("dcsref: unit series %s has no helper support", s))
	}
	unitViews[s] = out
	return out
}

// ThreatForUnitType returns the threat systems (threats ids, sorted) unit
// type unitType is a component or the emitter of; an error for an id no unit
// series holds (ThreatsForUnit returns none for it).
func ThreatForUnitType(unitType string) ([]string, error) {
	if _, ok := unitOf(unitType); !ok {
		return nil, notFound("no unit type %q", unitType)
	}
	out := ThreatsForUnit(unitType)
	if out == nil {
		out = []string{}
	}
	return out, nil
}

// EarthRadiusM is the mean Earth radius (IUGG) of the spherical ring geometry.
const EarthRadiusM = 6371008.8

// pyMod is Python's float %: the result has the sign of b.
func pyMod(a, b float64) float64 {
	m := math.Mod(a, b)
	if m != 0 {
		if (b < 0) != (m < 0) {
			m += b
		}
	} else {
		m = math.Copysign(0, b)
	}
	return m
}

// destination is [lon, lat] distM from (lat, lon) on bearing degrees, on a
// sphere of radius EarthRadiusM; longitude in [-180, 180).
func destination(lat, lon, bearing, distM float64) []float64 {
	phi, lam := lat*degToRad, lon*degToRad
	theta, delta := bearing*degToRad, distM/EarthRadiusM
	phi2 := math.Asin(math.Sin(phi)*math.Cos(delta) + math.Cos(phi)*math.Sin(delta)*math.Cos(theta))
	lam2 := lam + math.Atan2(
		math.Sin(theta)*math.Sin(delta)*math.Cos(phi),
		math.Cos(delta)-math.Sin(phi)*math.Sin(phi2),
	)
	lon2 := pyMod(lam2*radToDeg+180, 360) - 180
	return []float64{lon2, phi2 * radToDeg}
}

// ring is a closed ring of segments points; bearing 0 first, then clockwise
// (increasing bearing) or counterclockwise.
func ring(lat, lon, km float64, segments int, clockwise bool) [][]float64 {
	points := make([][]float64, 0, segments+1)
	for i := range segments + 1 {
		step := i % segments
		var bearing float64
		if clockwise {
			bearing = float64(360*step) / float64(segments)
		} else {
			bearing = pyMod(float64(360*(segments-step))/float64(segments), 360)
		}
		points = append(points, destination(lat, lon, bearing, km*1000))
	}
	return points
}

// ThreatRingProperties are the properties of a threat ring feature.
type ThreatRingProperties struct {
	Threat string `json:"threat"`
	ThreatLimits
}

// ThreatRingGeometry is a GeoJSON Polygon: [lon, lat] rings.
type ThreatRingGeometry struct {
	Type        string        `json:"type"`
	Coordinates [][][]float64 `json:"coordinates"`
}

// ThreatRingFeature is a GeoJSON Feature.
type ThreatRingFeature struct {
	Type       string               `json:"type"`
	Properties ThreatRingProperties `json:"properties"`
	Geometry   ThreatRingGeometry   `json:"geometry"`
}

// ThreatRingCollection is a GeoJSON FeatureCollection.
type ThreatRingCollection struct {
	Type     string              `json:"type"`
	Features []ThreatRingFeature `json:"features"`
}

// ThreatRingGeoJSON returns a GeoJSON FeatureCollection of one Polygon
// feature: the threat's RMaxKm ring around (lat, lon) (counterclockwise, as
// RFC 7946 wants an exterior ring) with its RMinKm ring as a clockwise hole
// when RMinKm > 0; segments points per ring plus the closing one. Properties:
// threat and the ThreatRange fields. An error for a threat without RMaxKm or
// segments < 3.
func ThreatRingGeoJSON(threatID string, lat, lon float64, segments int) (ThreatRingCollection, error) {
	if segments < 3 {
		return ThreatRingCollection{}, invalid("segments must be at least 3, got %d", segments)
	}
	rng, err := ThreatRange(threatID)
	if err != nil {
		return ThreatRingCollection{}, err
	}
	if rng.RMaxKm == nil {
		return ThreatRingCollection{}, invalid("threat %s has no engagement range", threatID)
	}
	rings := [][][]float64{ring(lat, lon, *rng.RMaxKm, segments, false)}
	if rng.RMinKm != nil && *rng.RMinKm > 0 {
		rings = append(rings, ring(lat, lon, *rng.RMinKm, segments, true))
	}
	return ThreatRingCollection{
		Type: "FeatureCollection",
		Features: []ThreatRingFeature{{
			Type:       "Feature",
			Properties: ThreatRingProperties{Threat: threatID, ThreatLimits: rng},
			Geometry:   ThreatRingGeometry{Type: "Polygon", Coordinates: rings},
		}},
	}, nil
}

// Classification --------------------------------------------------------------

type classRule struct {
	Role  string                         `json:"role"`
	Class string                         `json:"class"`
	When  map[string]map[string][]string `json:"when"`
}

type classification struct {
	AircraftRoles []classRule `json:"aircraftRoles"`
	UnitClasses   []classRule `json:"unitClasses"`
}

func classRules() classification { return index[classification]("classification") }

func (r classRule) matches(facts map[string][]string) bool {
	for fact, tests := range r.When {
		have := facts[fact]
		held := func(v string) bool { return slices.Contains(have, v) }
		if anyOf, ok := tests["any"]; ok && !slices.ContainsFunc(anyOf, held) {
			return false
		}
		if all, ok := tests["all"]; ok {
			for _, v := range all {
				if !slices.Contains(have, v) {
					return false
				}
			}
		}
		if none, ok := tests["none"]; ok && slices.ContainsFunc(none, held) {
			return false
		}
	}
	return true
}

// AircraftRoles returns the sorted roles of aircraft aircraftID: those of
// every matching aircraftRoles rule of the classification index (facts
// attributes, kind, tasks, defaultTask, isTanker).
func AircraftRoles(aircraftID string) ([]string, error) {
	a, ok := LoadAircraft()[aircraftID]
	if !ok {
		return nil, notFound("no aircraft record %q", aircraftID)
	}
	facts := map[string][]string{
		"attributes": a.Attributes,
		"kind":       {string(a.Kind)},
	}
	for _, t := range a.Tasks {
		facts["tasks"] = append(facts["tasks"], t.Name)
	}
	if a.DefaultTask != nil {
		facts["defaultTask"] = []string{a.DefaultTask.Name}
	}
	if a.Refuelling != nil && a.Refuelling.IsTanker != nil && a.Refuelling.IsTanker.Truthy() {
		facts["isTanker"] = []string{"true"}
	}
	roles := []string{}
	for _, r := range classRules().AircraftRoles {
		if r.matches(facts) {
			roles = append(roles, r.Role)
		}
	}
	slices.Sort(roles)
	return slices.Compact(roles), nil
}

// UnitClass returns the class of unit unitID (any unit series): that of the
// first matching unitClasses rule of the classification index (facts series,
// attributes, kind), else "other".
func UnitClass(unitID string) (string, error) {
	u, ok := unitOf(unitID)
	if !ok {
		return "", notFound("no unit type %q", unitID)
	}
	facts := map[string][]string{
		"series":     {string(u.series)},
		"attributes": u.attrs,
		"kind":       u.kind,
	}
	for _, r := range classRules().UnitClasses {
		if r.matches(facts) {
			return r.Class, nil
		}
	}
	return "other", nil
}

// Loadouts --------------------------------------------------------------------

// FitConflict is a store FitStores could not place.
type FitConflict struct {
	// Index is the position in the requested list.
	Index int    `json:"index"`
	CLSID string `json:"clsid"`
	// Reason is "unsupported" (no station accepts the store), "noFreeStation"
	// (the stations accepting it are all needed by the stores listed before it)
	// or "loadoutRules" (every placement with them breaks a station's
	// forbidden/required rule).
	Reason string `json:"reason"`
}

// FitResult is a station -> CLSID assignment, or the conflicts preventing one.
type FitResult struct {
	Assignment map[int]string `json:"assignment,omitzero"`
	Conflicts  []FitConflict  `json:"conflicts,omitzero"`
}

// LoadoutMassResult is the mass breakdown LoadoutMass returns.
type LoadoutMassResult struct {
	TotalKg      float64  `json:"totalKg"`
	EmptyKg      float64  `json:"emptyKg"`
	StoresKg     float64  `json:"storesKg"`
	FuelKg       float64  `json:"fuelKg"`
	MaxTakeoffKg *float64 `json:"maxTakeoffKg,omitzero"`
	OverMtow     *bool    `json:"overMtow,omitzero"`
}

func stations(aircraftID string) ([]Station, error) {
	a, ok := LoadAircraft()[aircraftID]
	if !ok {
		return nil, notFound("no aircraft record %q", aircraftID)
	}
	out := slices.Clone(a.Stations)
	sort.SliceStable(out, func(i, j int) bool { return out[i].Station < out[j].Station })
	return out, nil
}

func store(clsid string) (Store, error) {
	s, ok := LoadStores()[clsid]
	if !ok {
		return Store{}, notFound("no stores record %q", clsid)
	}
	return s, nil
}

// StationsAccepting returns the station numbers (ascending) of aircraft
// aircraftID accepting store clsid.
func StationsAccepting(aircraftID, clsid string) ([]int, error) {
	if _, err := store(clsid); err != nil {
		return nil, err
	}
	sts, err := stations(aircraftID)
	if err != nil {
		return nil, err
	}
	out := []int{}
	for _, s := range sts {
		if accepted(s, clsid) != nil {
			out = append(out, int(s.Station))
		}
	}
	return out, nil
}

func accepted(s Station, clsid string) *StationStore {
	for i := range s.Accepts {
		if s.Accepts[i].CLSID == clsid {
			return &s.Accepts[i]
		}
	}
	return nil
}

// CanMount reports whether station station of aircraft aircraftID accepts
// store clsid; an error for a station the aircraft lacks.
func CanMount(aircraftID string, station int, clsid string) (bool, error) {
	if _, err := store(clsid); err != nil {
		return false, err
	}
	sts, err := stations(aircraftID)
	if err != nil {
		return false, err
	}
	for _, s := range sts {
		if s.Station == float64(station) {
			return accepted(s, clsid) != nil, nil
		}
	}
	return false, notFound("aircraft %s has no station %d", aircraftID, station)
}

// matching is the size of a maximum matching of stores (each a list of
// candidate stations) to distinct stations (Kuhn's augmenting paths).
func matching(options [][]int) int {
	owner := map[int]int{}
	var augment func(i int, seen map[int]bool) bool
	augment = func(i int, seen map[int]bool) bool {
		for _, s := range options[i] {
			if seen[s] {
				continue
			}
			seen[s] = true
			if o, ok := owner[s]; !ok || augment(o, seen) {
				owner[s] = i
				return true
			}
		}
		return false
	}
	n := 0
	for i := range options {
		if augment(i, map[int]bool{}) {
			n++
		}
	}
	return n
}

type ruleKey struct {
	station int
	clsid   string
}

type fitRules map[ruleKey]*StationStore

// forbids reports whether occupant (ok false: empty) of the rule's station
// breaks forbidden rule r: it holds one of r.Clsids, or any store with
// r.AnyStore.
func forbids(r StationForbidden, occupant string, ok bool) bool {
	return ok && ((r.AnyStore != nil && *r.AnyStore) || slices.Contains(r.Clsids, occupant))
}

// unmet reports whether occupant (ok false: empty) of the rule's station
// breaks required rule r: it holds none of r.Clsids, or is empty without
// r.AllowEmpty.
func unmet(r StationRequired, occupant string, ok bool) bool {
	if !ok {
		return !r.AllowEmpty
	}
	return !slices.Contains(r.Clsids, occupant)
}

// allowed reports whether store c can join a (station -> CLSID) on station s
// without breaking a rule of either side; a required rule on a station still
// empty is left to the complete assignment.
func (rules fitRules) allowed(a map[int]string, s int, c string) bool {
	occupant := func(t int) (string, bool) {
		if t == s {
			return c, true
		}
		o, ok := a[t]
		return o, ok
	}
	own := rules[ruleKey{s, c}]
	for _, r := range own.Forbidden {
		if o, ok := occupant(int(r.Station)); ok && forbids(r, o, true) {
			return false
		}
	}
	for _, r := range own.Required {
		if o, ok := occupant(int(r.Station)); ok && unmet(r, o, true) {
			return false
		}
	}
	for t, o := range a {
		theirs := rules[ruleKey{t, o}]
		for _, r := range theirs.Forbidden {
			if int(r.Station) == s && forbids(r, c, true) {
				return false
			}
		}
		for _, r := range theirs.Required {
			if int(r.Station) == s && unmet(r, c, true) {
				return false
			}
		}
	}
	return true
}

// complete reports whether stores of pool (indexes, each used once) can fill
// every station a required rule of a needs, keeping every rule; a is
// restored.
func (rules fitRules) complete(a map[int]string, clsids []string, options [][]int, pool []int) bool {
	var need *StationRequired
	for t, o := range a {
		for _, r := range rules[ruleKey{t, o}].Required {
			occupant, ok := a[int(r.Station)]
			if unmet(r, occupant, ok) {
				need = &r
				break
			}
		}
		if need != nil {
			break
		}
	}
	if need == nil {
		return true
	}
	s := int(need.Station)
	if _, used := a[s]; used {
		return false
	}
	tried := map[string]bool{}
	for n, j := range pool {
		c := clsids[j]
		if tried[c] || !slices.Contains(need.Clsids, c) || !slices.Contains(options[j], s) {
			continue
		}
		tried[c] = true
		if !rules.allowed(a, s, c) {
			continue
		}
		a[s] = c
		done := rules.complete(a, clsids, options, slices.Delete(slices.Clone(pool), n, n+1))
		delete(a, s)
		if done {
			return true
		}
	}
	return false
}

// place returns the first assignment of stores idx (in order, each on its
// lowest station that leaves the rest placeable) keeping every rule, stations
// required rules need left empty only where stores of pool can fill them; nil
// if none.
func (rules fitRules) place(clsids []string, options [][]int, idx, pool []int) map[int]string {
	a := map[int]string{}
	at := map[int]int{}
	var step func(k int) bool
	step = func(k int) bool {
		if k == len(idx) {
			return rules.complete(a, clsids, options, pool)
		}
		i := idx[k]
		// A store equal to an earlier one goes above it (same fits, fewer tries).
		low, hasLow := 0, false
		for _, j := range idx[:k] {
			if clsids[j] == clsids[i] && (!hasLow || at[j] > low) {
				low, hasLow = at[j], true
			}
		}
		for _, s := range options[i] {
			if _, used := a[s]; used || (hasLow && s <= low) || !rules.allowed(a, s, clsids[i]) {
				continue
			}
			a[s], at[i] = clsids[i], s
			rest := make([][]int, 0, len(idx)-k-1)
			for _, j := range idx[k+1:] {
				var free []int
				for _, t := range options[j] {
					if _, used := a[t]; !used {
						free = append(free, t)
					}
				}
				rest = append(rest, free)
			}
			if matching(rest) == len(rest) && step(k+1) {
				return true
			}
			delete(a, s)
			delete(at, i)
		}
		return false
	}
	if !step(0) {
		return nil
	}
	return a
}

// FitStores puts each store of clsids on its own station of aircraftID.
//
// Rule: a store no station accepts is "unsupported"; the others are taken in
// list order, each kept while all kept stores still fit on distinct stations
// (else "noFreeStation") and some such placement, with stores later in the
// list filling the stations its required rules need, keeps every station's
// forbidden/required rules (else "loadoutRules"; a required station must hold
// a listed store, or be empty where it AllowEmpty). Every station accepting a
// store is a candidate, whatever its Type, as in the mission editor. With no
// conflicts, each store in list order gets the lowest-numbered station that
// leaves the rest placeable (Assignment); otherwise Conflicts.
func FitStores(aircraftID string, clsids []string) (FitResult, error) {
	// Same lookup order, hence same error, as StationsAccepting per store.
	for _, c := range clsids[:min(1, len(clsids))] {
		if _, err := store(c); err != nil {
			return FitResult{}, err
		}
	}
	sts, err := stations(aircraftID)
	if err != nil {
		return FitResult{}, err
	}
	for _, c := range clsids[min(1, len(clsids)):] {
		if _, err := store(c); err != nil {
			return FitResult{}, err
		}
	}
	// at[c]: 1 + index in sts of the last station listed for requested c.
	at := make(map[string]int, len(clsids))
	for _, c := range clsids {
		at[c] = 0
	}
	rules := fitRules{}
	accepting := map[string][]int{}
	for n, s := range sts {
		for j := range s.Accepts {
			c := s.Accepts[j].CLSID
			last, ok := at[c]
			if !ok {
				continue
			}
			rules[ruleKey{int(s.Station), c}] = &s.Accepts[j]
			if last != n+1 {
				at[c] = n + 1
				accepting[c] = append(accepting[c], int(s.Station))
			}
		}
	}
	options := make([][]int, len(clsids))
	ruled := false
	for i, c := range clsids {
		options[i] = accepting[c]
		if options[i] == nil {
			options[i] = []int{}
		}
		for _, s := range options[i] {
			e := rules[ruleKey{s, c}]
			ruled = ruled || len(e.Forbidden) > 0 || len(e.Required) > 0
		}
	}
	later := func(i int) []int {
		var pool []int
		for k := i + 1; k < len(clsids); k++ {
			if len(options[k]) > 0 {
				pool = append(pool, k)
			}
		}
		return pool
	}
	var conflicts []FitConflict
	var kept []int
	var placed map[int]string
	for i, opts := range options {
		trial := make([][]int, 0, len(kept)+1)
		for _, k := range kept {
			trial = append(trial, options[k])
		}
		reason := ""
		switch {
		case len(opts) == 0:
			reason = "unsupported"
		case matching(append(trial, opts)) != len(kept)+1:
			reason = "noFreeStation"
		case ruled:
			// Without rules every placement that fits keeps them.
			placed = rules.place(clsids, options, append(slices.Clone(kept), i), later(i))
			if placed == nil {
				reason = "loadoutRules"
			}
		}
		if reason == "" {
			kept = append(kept, i)
		} else {
			conflicts = append(conflicts, FitConflict{Index: i, CLSID: clsids[i], Reason: reason})
		}
	}
	if len(conflicts) > 0 {
		return FitResult{Conflicts: conflicts}, nil
	}
	// With no conflicts the last store's placement is that of every store.
	assignment := placed
	if assignment == nil {
		assignment = rules.place(clsids, options, kept, nil)
	}
	if assignment == nil {
		assignment = map[int]string{}
	}
	return FitResult{Assignment: assignment}, nil
}

// LoadoutMass returns the mass of aircraft aircraftID with loadout (station
// -> store CLSID) and fuelKg of internal fuel (nil: aero.internalFuelKg,
// full): EmptyKg (aero.emptyMassKg) + StoresKg (each store's aero.massKg,
// DCS's launcher Weight: rack and contents included) + FuelKg; with
// aero.maxTakeoffKg, MaxTakeoffKg and OverMtow. An error for a station that
// does not accept its store, a store without a mass, a missing empty mass,
// fuel not given where the aircraft has no internalFuelKg, or fuel outside
// 0..internalFuelKg.
func LoadoutMass(aircraftID string, loadout map[int]string, fuelKg *float64) (LoadoutMassResult, error) {
	a, ok := LoadAircraft()[aircraftID]
	if !ok {
		return LoadoutMassResult{}, notFound("no aircraft record %q", aircraftID)
	}
	aero := a.Aero
	if aero.EmptyMassKg == nil {
		return LoadoutMassResult{}, invalid("aircraft %s has no aero.emptyMassKg", aircraftID)
	}
	capacity := aero.InternalFuelKg
	var fuel float64
	if fuelKg == nil {
		if capacity == nil {
			return LoadoutMassResult{}, invalid("aircraft %s has no aero.internalFuelKg; pass fuelKg", aircraftID)
		}
		fuel = *capacity
	} else {
		fuel = *fuelKg
	}
	if fuel < 0 || (capacity != nil && fuel > *capacity) {
		return LoadoutMassResult{}, invalid("fuel %v kg outside 0..capacity for %s", fuel, aircraftID)
	}
	storesKg := 0.0
	stationNums := make([]int, 0, len(loadout))
	for s := range loadout {
		stationNums = append(stationNums, s)
	}
	slices.Sort(stationNums)
	for _, station := range stationNums {
		clsid := loadout[station]
		ok, err := CanMount(aircraftID, station, clsid)
		if err != nil {
			return LoadoutMassResult{}, err
		}
		if !ok {
			return LoadoutMassResult{}, invalid("station %d of %s does not accept %s", station, aircraftID, clsid)
		}
		s, _ := store(clsid)
		if s.Aero.MassKg == nil {
			return LoadoutMassResult{}, invalid("store %s has no aero.massKg", clsid)
		}
		storesKg += *s.Aero.MassKg
	}
	empty := *aero.EmptyMassKg
	total := empty + storesKg + fuel
	out := LoadoutMassResult{TotalKg: total, EmptyKg: empty, StoresKg: storesKg, FuelKg: fuel}
	if aero.MaxTakeoffKg != nil {
		mtow := *aero.MaxTakeoffKg
		over := total > mtow
		out.MaxTakeoffKg, out.OverMtow = &mtow, &over
	}
	return out, nil
}

// Radios ----------------------------------------------------------------------

// FrequencyRange is a tunable range of a radio.
type FrequencyRange struct {
	MinMHz float64 `json:"minMHz"`
	MaxMHz float64 `json:"maxMHz"`
	// Modulations are DCS MODULATION_* names.
	Modulations []string `json:"modulations"`
}

// RadioTuning is what RadioBands returns per radio.
type RadioTuning struct {
	// Index is <index> of the radio id <aircraft>__radio<index> (DCS
	// panelRadio order, from 0).
	Index   int              `json:"index"`
	ID      string           `json:"id"`
	Band    RadioBand        `json:"band"`
	Ranges  []FrequencyRange `json:"ranges"`
	Presets float64          `json:"presets"`
	Guard   bool             `json:"guard"`
	StepKHz *float64         `json:"stepKHz,omitzero"`
}

// FrequencyCheck is the result of IsValidFrequency; Reason is "outOfRange"
// or "offStep" when not OK.
type FrequencyCheck struct {
	OK     bool   `json:"ok"`
	Reason string `json:"reason,omitempty"`
}

const radioSep = "__radio"

func isDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range []byte(s) {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

// RadioBands returns the radios of aircraft aircraftID by index: band,
// tunable ranges (the DCS range segments) with their modulations, preset
// count, guard coverage and StepKHz where the data gives one.
func RadioBands(aircraftID string) ([]RadioTuning, error) {
	a, ok := LoadAircraft()[aircraftID]
	if !ok {
		return nil, notFound("no aircraft record %q", aircraftID)
	}
	radios := LoadRadios()
	out := []RadioTuning{}
	for _, rid := range a.Radios {
		r, ok := radios[rid]
		if !ok {
			return nil, notFound("no radios record %q", rid)
		}
		cut := strings.LastIndex(rid, radioSep)
		if cut < 0 || rid[:cut] != aircraftID || !isDigits(rid[cut+len(radioSep):]) {
			return nil, invalid("radio id %q is not %s%s<index>", rid, aircraftID, radioSep)
		}
		index, err := strconv.Atoi(rid[cut+len(radioSep):])
		if err != nil {
			return nil, invalid("radio id %q: %v", rid, err)
		}
		ranges := make([]FrequencyRange, 0, len(r.Segments))
		for _, s := range r.Segments {
			ranges = append(ranges, FrequencyRange{
				MinMHz:      s.MinMHz,
				MaxMHz:      s.MaxMHz,
				Modulations: []string{s.ModulationName},
			})
		}
		out = append(out, RadioTuning{
			Index:   index,
			ID:      rid,
			Band:    r.Band,
			Ranges:  ranges,
			Presets: r.Presets,
			Guard:   r.Guard,
			StepKHz: r.StepKHz,
		})
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Index < out[j].Index })
	return out, nil
}

// StepTolerance is the largest distance from a tuning step, in steps, still
// on the step grid.
const StepTolerance = 1e-6

// IsValidFrequency reports whether radio radioIndex of aircraftID tunes mhz:
// within a range (else "outOfRange") and, with StepKHz, on the step grid
// counted from 0 Hz ("offStep"). An error for a radio the aircraft lacks.
func IsValidFrequency(aircraftID string, radioIndex int, mhz float64) (FrequencyCheck, error) {
	bands, err := RadioBands(aircraftID)
	if err != nil {
		return FrequencyCheck{}, err
	}
	for _, r := range bands {
		if r.Index != radioIndex {
			continue
		}
		if !slices.ContainsFunc(r.Ranges, func(g FrequencyRange) bool { return g.MinMHz <= mhz && mhz <= g.MaxMHz }) {
			return FrequencyCheck{OK: false, Reason: "outOfRange"}, nil
		}
		if r.StepKHz != nil {
			steps := mhz * 1000 / *r.StepKHz
			if math.Abs(steps-math.RoundToEven(steps)) > StepTolerance {
				return FrequencyCheck{OK: false, Reason: "offStep"}, nil
			}
		}
		return FrequencyCheck{OK: true}, nil
	}
	return FrequencyCheck{}, notFound("aircraft %s has no radio %d", aircraftID, radioIndex)
}

// Weapons ---------------------------------------------------------------------

// WeaponDetails is a weapon record's fields as the data gives them (no
// Sources), its Warhead resolved to the warhead record.
type WeaponDetails struct {
	Weapon
	Warhead *Warhead `json:"warhead,omitzero"`
}

// Launchers are the unit types launching a weapon, each list sorted.
type Launchers struct {
	Aircraft       []string `json:"aircraft"`
	GroundVehicles []string `json:"groundVehicles"`
	Ships          []string `json:"ships"`
}

func weaponID(idOrCLSID string) (string, error) {
	if _, ok := LoadWeapons()[idOrCLSID]; ok {
		return idOrCLSID, nil
	}
	s, ok := LoadStores()[idOrCLSID]
	if !ok {
		return "", notFound("no weapon or store %q", idOrCLSID)
	}
	var delivered []string
	for _, d := range s.Delivers {
		delivered = append(delivered, d.Weapon)
	}
	slices.Sort(delivered)
	delivered = slices.Compact(delivered)
	if len(delivered) != 1 {
		return "", invalid("store %s delivers %d weapon types, not one", idOrCLSID, len(delivered))
	}
	return delivered[0], nil
}

// WeaponInfo returns the weapon idOrCLSID names: a weapon id, else the CLSID
// of a store delivering exactly one weapon type (an ErrInvalid error for a
// store delivering several or none). Fields are the weapon record's (Sources
// dropped), with Warhead the warhead record.
func WeaponInfo(idOrCLSID string) (WeaponDetails, error) {
	id, err := weaponID(idOrCLSID)
	if err != nil {
		return WeaponDetails{}, err
	}
	w, ok := LoadWeapons()[id]
	if !ok {
		return WeaponDetails{}, notFound("no weapons record %q", id)
	}
	w.Sources = nil
	out := WeaponDetails{Weapon: w}
	if w.Warhead != nil {
		wh, ok := LoadWarheads()[*w.Warhead]
		if !ok {
			return WeaponDetails{}, notFound("no warheads record %q", *w.Warhead)
		}
		out.Warhead = &wh
	}
	return out, nil
}

func surfaceLaunchers(weapons func(id string) []WeaponSystem, ids []string, weaponID string) []string {
	out := []string{}
	for _, id := range ids {
		if slices.ContainsFunc(weapons(id), func(ws WeaponSystem) bool { return slices.Contains(ws.Weapons, weaponID) }) {
			out = append(out, id)
		}
	}
	return out
}

// LaunchPlatforms returns the unit types launching weapon weaponID:
// Aircraft with a station accepting a store that delivers it (the carriers
// index), GroundVehicles and Ships with a launcher (WeaponSystems) whose
// Weapons hold it.
func LaunchPlatforms(weaponID string) (Launchers, error) {
	if _, ok := LoadWeapons()[weaponID]; !ok {
		return Launchers{}, notFound("no weapons record %q", weaponID)
	}
	aircraft := AircraftCarrying(weaponID)
	if aircraft == nil {
		aircraft = []string{}
	}
	vehicles, ships := LoadGroundVehicles(), LoadShips()
	return Launchers{
		Aircraft: aircraft,
		GroundVehicles: surfaceLaunchers(func(id string) []WeaponSystem { return vehicles[id].WeaponSystems },
			sortedKeys(vehicles), weaponID),
		Ships: surfaceLaunchers(func(id string) []WeaponSystem { return ships[id].WeaponSystems },
			sortedKeys(ships), weaponID),
	}, nil
}

// ModelToUnits returns the unit ids of every unit series whose model shape
// is shape, sorted. Names compare as NameKey does (trimmed, ASCII
// case-insensitive): DCS finds models by file name, and Windows file names
// ignore case.
func ModelToUnits(shape string) []string {
	key := NameKey(shape)
	out := []string{}
	for _, s := range meta().UnitSeries {
		for id, u := range unitsOf(s) {
			if u.model != nil && u.model.Shape != nil && NameKey(*u.model.Shape) == key {
				out = append(out, id)
			}
		}
	}
	slices.Sort(out)
	return out
}

// SensorSummary is a sensor of a unit: its id, kind and detection range.
type SensorSummary struct {
	ID               string     `json:"id"`
	Kind             SensorKind `json:"kind"`
	DetectionRangeKm *float64   `json:"detectionRangeKm,omitzero"`
}

// UnitDetectionInfo is a unit's detection fields as the data gives them, and
// its sensors.
type UnitDetectionInfo struct {
	UnitDetection
	Sensors []SensorSummary `json:"sensors"`
}

// UnitDetectionOf returns the detection values of unit unitID (any unit
// series): its detection fields, and Sensors, its sensor ids in record order
// with each sensor's kind and detection range (when given).
func UnitDetectionOf(unitID string) (UnitDetectionInfo, error) {
	u, ok := unitOf(unitID)
	if !ok {
		return UnitDetectionInfo{}, notFound("no unit type %q", unitID)
	}
	out := UnitDetectionInfo{Sensors: []SensorSummary{}}
	if u.detection != nil {
		out.UnitDetection = *u.detection
	}
	sensors := LoadSensors()
	for _, id := range u.sensors {
		s, ok := sensors[id]
		if !ok {
			return UnitDetectionInfo{}, notFound("no sensors record %q", id)
		}
		out.Sensors = append(out.Sensors, SensorSummary{ID: id, Kind: s.Kind, DetectionRangeKm: s.DetectionRangeKm})
	}
	return out, nil
}

// TACAN and navaids -------------------------------------------------------------

// TacanFrequencies is the frequency pair of a TACAN/DME channel for one side.
type TacanFrequencies struct {
	// TxMHz is the transmit frequency of the side the role names.
	TxMHz float64 `json:"txMHz"`
	// RxMHz is the receive frequency of that side.
	RxMHz float64 `json:"rxMHz"`
	// PairedVhfMHz is the VOR/ILS frequency the channel pairs with, when it
	// pairs.
	PairedVhfMHz *float64 `json:"pairedVhfMHz,omitzero"`
}

// TacanChannelBand is a TACAN channel and its band, "X" or "Y".
type TacanChannelBand struct {
	Channel int    `json:"channel"`
	Band    string `json:"band"`
}

type channelRange struct {
	From    int     `json:"from"`
	To      int     `json:"to"`
	Offset  float64 `json:"offset"`
	BaseKHz float64 `json:"baseKHz"`
}

type tacanPlan struct {
	Channels struct {
		First int `json:"first"`
		Last  int `json:"last"`
	} `json:"channels"`
	Bands            []string `json:"bands"`
	InterrogationMHz struct {
		Base float64 `json:"base"`
	} `json:"interrogationMHz"`
	ReplyOffsetMHz map[string][]channelRange `json:"replyOffsetMHz"`
	VhfPairing     struct {
		Ranges        []channelRange     `json:"ranges"`
		StepKHz       float64            `json:"stepKHz"`
		BandOffsetKHz map[string]float64 `json:"bandOffsetKHz"`
	} `json:"vhfPairing"`
}

func plan() tacanPlan { return index[tacanPlan]("tacan") }

func rangeOf(ranges []channelRange, channel int) (channelRange, bool) {
	for _, r := range ranges {
		if r.From <= channel && channel <= r.To {
			return r, true
		}
	}
	return channelRange{}, false
}

// IsValidTacan reports whether channel (an integer) and band name a channel
// of the tacan plan (1-126, X or Y).
func IsValidTacan(channel float64, band string) bool {
	p := plan()
	return channel == math.Floor(channel) &&
		float64(p.Channels.First) <= channel && channel <= float64(p.Channels.Last) &&
		slices.Contains(p.Bands, band)
}

// tacan returns the interrogation MHz, reply MHz and paired VHF MHz (nil
// when unpaired) of a valid channel.
func tacan(channel int, band string) (float64, float64, *float64) {
	p := plan()
	air := p.InterrogationMHz.Base + float64(channel-p.Channels.First)
	reply, _ := rangeOf(p.ReplyOffsetMHz[band], channel)
	var vhf *float64
	if hit, ok := rangeOf(p.VhfPairing.Ranges, channel); ok {
		khz := hit.BaseKHz + float64(channel-hit.From)*p.VhfPairing.StepKHz
		v := (khz + p.VhfPairing.BandOffsetKHz[band]) / 1000
		vhf = &v
	}
	return air, air + reply.Offset, vhf
}

// TacanFrequency returns the frequencies of TACAN/DME channel channel band
// for the airborne interrogator (role "air": transmits the interrogation,
// receives the reply) or the ground beacon ("ground": the other way round),
// from the tacan index (ICAO Annex 10 Table A; tools/datamine/overlays.yaml).
// An ErrInvalid error for a channel IsValidTacan rejects or another role.
func TacanFrequency(channel int, band, role string) (TacanFrequencies, error) {
	if !IsValidTacan(float64(channel), band) {
		return TacanFrequencies{}, invalid("no TACAN channel %d%s", channel, band)
	}
	air, reply, vhf := tacan(channel, band)
	switch role {
	case "air":
		return TacanFrequencies{TxMHz: air, RxMHz: reply, PairedVhfMHz: vhf}, nil
	case "ground":
		return TacanFrequencies{TxMHz: reply, RxMHz: air, PairedVhfMHz: vhf}, nil
	}
	return TacanFrequencies{}, invalid("role must be air or ground, got %q", role)
}

// FrequencyToleranceMHz is the largest difference at which TacanChannel
// counts a match.
const FrequencyToleranceMHz = 1e-6

// TacanChannel returns every channel (sorted by channel, then band) whose
// role side transmits on mhz ("air": the interrogation, which X and Y
// channels share; "ground": the reply) or, for "vhf", that pairs with VOR/ILS
// frequency mhz. Empty when none does.
func TacanChannel(mhz float64, role string) ([]TacanChannelBand, error) {
	if role != "air" && role != "ground" && role != "vhf" {
		return nil, invalid("role must be air, ground or vhf, got %q", role)
	}
	p := plan()
	out := []TacanChannelBand{}
	for ch := p.Channels.First; ch <= p.Channels.Last; ch++ {
		for _, band := range p.Bands {
			air, reply, vhf := tacan(ch, band)
			value := map[string]*float64{"air": &air, "ground": &reply, "vhf": vhf}[role]
			if value != nil && math.Abs(*value-mhz) <= FrequencyToleranceMHz {
				out = append(out, TacanChannelBand{Channel: ch, Band: band})
			}
		}
	}
	return out, nil
}

func airbase(airbaseID string) (Airbase, error) {
	a, ok := LoadAirbases()[airbaseID]
	if !ok {
		return Airbase{}, notFound("no airbases record %q", airbaseID)
	}
	return a, nil
}

// NavaidsFor returns the navaids ids (ILS/PRMG) of airbase airbaseID, sorted.
func NavaidsFor(airbaseID string) ([]string, error) {
	a, err := airbase(airbaseID)
	if err != nil {
		return nil, err
	}
	return sortedClone(a.Navaids), nil
}

// NavaidsForRunway returns the navaids ids of the runway end of airbaseID
// whose designator is runway (as NameKey), sorted; an ErrNotFound error for
// an end the airbase lacks.
func NavaidsForRunway(airbaseID, runway string) ([]string, error) {
	a, err := airbase(airbaseID)
	if err != nil {
		return nil, err
	}
	key := NameKey(runway)
	for _, rwy := range a.Runways {
		for _, d := range rwy.Directions {
			if NameKey(d.Designator) == key {
				return sortedClone(d.Navaids), nil
			}
		}
	}
	return nil, notFound("airbase %s has no runway end %q", airbaseID, runway)
}

func sortedClone(s []string) []string {
	out := append([]string{}, s...)
	slices.Sort(out)
	return out
}

// Runways and stands ------------------------------------------------------------

// RunwayThreshold is the runway spawn point at a runway end.
type RunwayThreshold struct {
	Lat        float64 `json:"lat"`
	Lon        float64 `json:"lon"`
	ElevationM float64 `json:"elevationM"`
}

// RunwayEnd is one runway end of an airbase.
type RunwayEnd struct {
	// Runway is the designator pair of the runway (13/31).
	Runway     string `json:"runway"`
	Designator string `json:"designator"`
	// Name is DCS's own name of the end.
	Name      string          `json:"name"`
	TrueDeg   float64         `json:"trueDeg"`
	MagDeg    float64         `json:"magDeg"`
	Threshold RunwayThreshold `json:"threshold"`
	LengthM   float64         `json:"lengthM"`
}

// RunwayChoice is the runway end BestRunway picks and its wind components.
type RunwayChoice struct {
	End RunwayEnd `json:"end"`
	// HeadwindKt is negative for a tailwind.
	HeadwindKt float64 `json:"headwindKt"`
	// CrosswindKt is the magnitude, from either side.
	CrosswindKt float64 `json:"crosswindKt"`
}

// NearbyAirbase is an airbase NearestAirbases found.
type NearbyAirbase struct {
	ID     string  `json:"id"`
	DistNm float64 `json:"distNm"`
	// BearingDeg is the initial true bearing from the given point to the
	// reference point.
	BearingDeg float64 `json:"bearingDeg"`
}

// RunwayEnds returns every runway end (runways, then directions, in data
// order) of airbaseID: bearings from its threshold along the runway, the
// threshold (the runway spawn point at that end) and the runway length.
// Empty for an airbase without runway data.
func RunwayEnds(airbaseID string) ([]RunwayEnd, error) {
	a, err := airbase(airbaseID)
	if err != nil {
		return nil, err
	}
	out := []RunwayEnd{}
	for _, rwy := range a.Runways {
		for _, d := range rwy.Directions {
			t := d.Threshold
			if t.ElevationM == nil {
				return nil, invalid("runway end %s of %s has no threshold elevation", d.Designator, airbaseID)
			}
			out = append(out, RunwayEnd{
				Runway:     rwy.Designator,
				Designator: d.Designator,
				Name:       d.Name,
				TrueDeg:    d.TrueBearingDeg,
				MagDeg:     d.MagneticBearingDeg,
				Threshold:  RunwayThreshold{Lat: t.Latitude, Lon: t.Longitude, ElevationM: *t.ElevationM},
				LengthM:    rwy.LengthM,
			})
		}
	}
	return out, nil
}

// WindToleranceKt is the difference below which BestRunway counts wind
// components equal.
const WindToleranceKt = 1e-9

func (a RunwayChoice) better(b RunwayChoice) bool {
	if math.Abs(a.HeadwindKt-b.HeadwindKt) > WindToleranceKt {
		return a.HeadwindKt > b.HeadwindKt
	}
	if math.Abs(a.CrosswindKt-b.CrosswindKt) > WindToleranceKt {
		return a.CrosswindKt < b.CrosswindKt
	}
	if a.End.LengthM != b.End.LengthM {
		return a.End.LengthM > b.End.LengthM
	}
	return a.End.Designator < b.End.Designator
}

// BestRunway returns the runway end of airbaseID facing the wind (blowing
// from windFromDegTrue at windKt): headwind windKt*cos(from - trueDeg),
// crosswind |windKt*sin(from - trueDeg)|. Most headwind wins; ties (within
// WindToleranceKt, as in calm air) go to the least crosswind, then the longer
// runway, then the lower designator (string order). An ErrInvalid error for a
// negative wind or an airbase without runway data.
func BestRunway(airbaseID string, windFromDegTrue, windKt float64) (RunwayChoice, error) {
	if !(windKt >= 0) {
		return RunwayChoice{}, invalid("wind speed must be >= 0 kt, got %v", windKt)
	}
	ends, err := RunwayEnds(airbaseID)
	if err != nil {
		return RunwayChoice{}, err
	}
	var best *RunwayChoice
	for _, end := range ends {
		a := (windFromDegTrue - end.TrueDeg) * degToRad
		cand := RunwayChoice{End: end, HeadwindKt: windKt * math.Cos(a), CrosswindKt: math.Abs(windKt * math.Sin(a))}
		if best == nil || cand.better(*best) {
			best = &cand
		}
	}
	if best == nil {
		return RunwayChoice{}, invalid("airbase %s has no runway data", airbaseID)
	}
	return *best, nil
}

// NmM is metres per international nautical mile.
const NmM = 1852.0

// NearestOptions filter NearestAirbases.
type NearestOptions struct {
	// MinRunwayM, when set, keeps airbases whose longestRunwayM reaches it
	// (those without runway data drop out).
	MinRunwayM *float64
	// Category, when not "", keeps airbases of that categoryName
	// (case-insensitive, e.g. AIRDROME).
	Category string
}

// NearestAirbases returns the n airbases of theatre (anything TheatreByName
// accepts) whose reference points lie nearest (lat, lon) by DistanceBearing,
// nearest first (ties by id), filtered by opts. An ErrInvalid error for n <
// 1 or a point out of range.
func NearestAirbases(theatre string, lat, lon float64, n int, opts NearestOptions) ([]NearbyAirbase, error) {
	if n < 1 {
		return nil, invalid("n must be at least 1, got %d", n)
	}
	t, ok := TheatreByName(theatre)
	if !ok {
		return nil, notFound("no theatre %q", theatre)
	}
	type hit struct {
		dist, bearing float64
		id            string
	}
	var found []hit
	for id, ab := range LoadAirbases() {
		p := ab.ReferencePoint
		if ab.Theatre != t.ID || p == nil {
			continue
		}
		if opts.MinRunwayM != nil && (ab.LongestRunwayM == nil || !(*ab.LongestRunwayM >= *opts.MinRunwayM)) {
			continue
		}
		if opts.Category != "" {
			name := ""
			if ab.CategoryName != nil {
				name = *ab.CategoryName
			}
			if NameKey(name) != NameKey(opts.Category) {
				continue
			}
		}
		db, err := DistanceBearing(lat, lon, p.Latitude, p.Longitude)
		if err != nil {
			return nil, err
		}
		found = append(found, hit{db.DistM, db.BearingDeg, id})
	}
	slices.SortFunc(found, func(a, b hit) int {
		if a.dist != b.dist {
			return cmpFloat(a.dist, b.dist)
		}
		if a.id != b.id {
			return strings.Compare(a.id, b.id)
		}
		return cmpFloat(a.bearing, b.bearing)
	})
	out := []NearbyAirbase{}
	for _, h := range found[:min(n, len(found))] {
		out = append(out, NearbyAirbase{ID: h.id, DistNm: h.dist / NmM, BearingDeg: h.bearing})
	}
	return out, nil
}

func cmpFloat(a, b float64) int {
	switch {
	case a < b:
		return -1
	case a > b:
		return 1
	}
	return 0
}

// StandsFor returns the termIndex of every stand of airbaseID taking
// aircraftID, ascending, by the mission editor's rule (StandLimits): wing
// span (else rotor diameter) < MaxWidthM, length < MaxLengthM, height <
// MaxHeightM (1000 when absent), and Helicopters (rotary) or Airplanes (fixed
// wing) true. Stands without limits are left out. An ErrInvalid error for an
// aircraft without those dimensions.
func StandsFor(airbaseID, aircraftID string) ([]int, error) {
	a, ok := LoadAircraft()[aircraftID]
	if !ok {
		return nil, notFound("no aircraft record %q", aircraftID)
	}
	d := a.Dimensions
	var width *float64
	if d != nil {
		width = d.WingSpanM
		if width == nil {
			width = d.RotorDiameterM
		}
	}
	if width == nil || d.LengthM == nil || d.HeightM == nil {
		return nil, invalid("aircraft %s lacks the dimensions stands check", aircraftID)
	}
	ab, err := airbase(airbaseID)
	if err != nil {
		return nil, err
	}
	out := []int{}
	for _, s := range ab.Stands {
		lim := s.Limits
		if lim == nil {
			continue
		}
		maxHeight := 1000.0
		if lim.MaxHeightM != nil {
			maxHeight = *lim.MaxHeightM
		}
		use := lim.Airplanes
		if a.Kind == AircraftKindRotary {
			use = lim.Helicopters
		}
		if *width < lim.MaxWidthM && *d.LengthM < lim.MaxLengthM && *d.HeightM < maxHeight && use {
			out = append(out, int(s.TermIndex))
		}
	}
	slices.Sort(out)
	return out, nil
}

// Countries, liveries and datalinks ---------------------------------------------

// CountryIDOf returns the id of the country whose name, shortName,
// internationalName, idName or oldId is nameOrAlias (as NameKey), else of the
// countryAliases index entry (tools/datamine/overlays.yaml); ok false if
// none.
func CountryIDOf(nameOrAlias string) (int, bool) {
	key := NameKey(nameOrAlias)
	countries := LoadCountries()
	for _, id := range sortedKeys(countries) {
		c := countries[id]
		for _, name := range []*string{&c.Name, c.ShortName, c.InternationalName, c.IDName, c.OldID} {
			if name != nil && NameKey(*name) == key {
				return int(c.ID), true
			}
		}
	}
	id, ok := index[map[string]int]("countryAliases")[key]
	return id, ok
}

// CountryName returns the DCS Name of country countryID.
func CountryName(countryID int) (string, error) {
	c, ok := LoadCountries()[strconv.Itoa(countryID)]
	if !ok {
		return "", notFound("no countries record %d", countryID)
	}
	return c.Name, nil
}

// LiveriesFor returns the ids of the liveries of unit type unitType (in their
// unitTypes), sorted.
func LiveriesFor(unitType string) ([]string, error) {
	return liveries(unitType, nil)
}

// LiveriesForCountry returns the ids of the liveries of unit type unitType
// offered to country countryID, sorted: those without countries (offered to
// every country) or whose countries hold it. A country of the
// allLiveryCountries index (the Combined Joint Task Forces, as the mission
// editor's loadLiveries.lua treats them; tools/datamine/overlays.yaml) gets
// every livery of the unit type.
func LiveriesForCountry(unitType string, countryID int) ([]string, error) {
	return liveries(unitType, &countryID)
}

func liveries(unitType string, country *int) ([]string, error) {
	if _, ok := unitOf(unitType); !ok {
		return nil, notFound("no unit type %q", unitType)
	}
	if country != nil {
		if _, err := CountryName(*country); err != nil {
			return nil, err
		}
		if _, all := index[map[string]string]("allLiveryCountries")[strconv.Itoa(*country)]; all {
			country = nil
		}
	}
	out := []string{}
	for id, lv := range LoadLiveries() {
		if slices.Contains(lv.UnitTypes, unitType) &&
			(country == nil || lv.Countries == nil || slices.Contains(lv.Countries, CountryID(*country))) {
			out = append(out, id)
		}
	}
	slices.Sort(out)
	return out, nil
}

// DatalinkInfo is a datalink record without its id.
type DatalinkInfo struct {
	DatalinkType            DatalinkType `json:"datalinkType"`
	CanBeLink16Donor        bool         `json:"canBeLink16Donor"`
	SupportsTeamMembers     bool         `json:"supportsTeamMembers"`
	SupportsCrossFlightTeam bool         `json:"supportsCrossFlightTeam"`
	MaxDonors               float64      `json:"maxDonors"`
	MaxTeamMembers          float64      `json:"maxTeamMembers"`
	Notes                   *string      `json:"notes,omitzero"`
}

// DatalinkCapability returns the datalink record of aircraft aircraftID
// (without id), or nil when it has none.
func DatalinkCapability(aircraftID string) (*DatalinkInfo, error) {
	a, ok := LoadAircraft()[aircraftID]
	if !ok {
		return nil, notFound("no aircraft record %q", aircraftID)
	}
	if a.Datalink == nil {
		return nil, nil
	}
	d, ok := LoadDatalink()[*a.Datalink]
	if !ok {
		return nil, notFound("no datalink record %q", *a.Datalink)
	}
	return &DatalinkInfo{
		DatalinkType:            d.DatalinkType,
		CanBeLink16Donor:        d.CanBeLink16Donor,
		SupportsTeamMembers:     d.SupportsTeamMembers,
		SupportsCrossFlightTeam: d.SupportsCrossFlightTeam,
		MaxDonors:               d.MaxDonors,
		MaxTeamMembers:          d.MaxTeamMembers,
		Notes:                   d.Notes,
	}, nil
}
