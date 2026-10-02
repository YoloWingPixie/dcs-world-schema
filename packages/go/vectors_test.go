package dcsref

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"testing"
)

// vectorFile is tools/package/tests/vectors/helpers.json, the conformance
// vectors the Python package (the reference) writes and every package runs;
// DCSREF_VECTORS overrides its directory.
func vectorFile() string {
	dir := os.Getenv("DCSREF_VECTORS")
	if dir == "" {
		dir = filepath.Join("..", "..", "tools", "package", "tests", "vectors")
	}
	return filepath.Join(dir, "helpers.json")
}

// vectorCase is {"fn", "args", "expect"} or, for inputs the helper must
// reject, {"fn", "args", "throws": true}.
type vectorCase struct {
	Fn     string            `json:"fn"`
	Args   []json.RawMessage `json:"args"`
	Expect json.RawMessage   `json:"expect"`
	Throws bool              `json:"throws"`
}

type vectorDoc struct {
	DCSVersion string `json:"dcsVersion"`
	Tolerance  struct {
		Abs float64 `json:"abs"`
		Rel float64 `json:"rel"`
	} `json:"tolerance"`
	Cases []vectorCase `json:"cases"`
}

func arg[T any](args []json.RawMessage, i int) T {
	var v T
	if err := json.Unmarshal(args[i], &v); err != nil {
		panic(fmt.Sprintf("argument %d %s: %v", i, args[i], err))
	}
	return v
}

func ret[T any](v T, err error) (any, error) { return v, err }

// vectorHelpers runs each vector function on its JSON arguments.
var vectorHelpers = map[string]func(a []json.RawMessage) (any, error){
	"theatreByName": func(a []json.RawMessage) (any, error) {
		if t, ok := TheatreByName(arg[string](a, 0)); ok {
			return t.ID, nil
		}
		return nil, nil
	},
	"toMapXZ": func(a []json.RawMessage) (any, error) {
		return ret(ToMapXZ(arg[string](a, 0), arg[float64](a, 1), arg[float64](a, 2)))
	},
	"toLatLon": func(a []json.RawMessage) (any, error) {
		return ret(ToLatLon(arg[string](a, 0), arg[float64](a, 1), arg[float64](a, 2)))
	},
	"threatRange":       func(a []json.RawMessage) (any, error) { return ret(ThreatRange(arg[string](a, 0))) },
	"threatForUnitType": func(a []json.RawMessage) (any, error) { return ret(ThreatForUnitType(arg[string](a, 0))) },
	"threatRingGeoJSON": func(a []json.RawMessage) (any, error) {
		return ret(ThreatRingGeoJSON(arg[string](a, 0), arg[float64](a, 1), arg[float64](a, 2), arg[int](a, 3)))
	},
	"aircraftRoles": func(a []json.RawMessage) (any, error) { return ret(AircraftRoles(arg[string](a, 0))) },
	"unitClass":     func(a []json.RawMessage) (any, error) { return ret(UnitClass(arg[string](a, 0))) },
	"stationsAccepting": func(a []json.RawMessage) (any, error) {
		return ret(StationsAccepting(arg[string](a, 0), arg[string](a, 1)))
	},
	"canMount": func(a []json.RawMessage) (any, error) {
		return ret(CanMount(arg[string](a, 0), arg[int](a, 1), arg[string](a, 2)))
	},
	"fitStores": func(a []json.RawMessage) (any, error) {
		return ret(FitStores(arg[string](a, 0), arg[[]string](a, 1)))
	},
	"loadoutMass": func(a []json.RawMessage) (any, error) {
		loadout := map[int]string{}
		for k, v := range arg[map[string]string](a, 1) {
			n, err := strconv.Atoi(k)
			if err != nil {
				return nil, err
			}
			loadout[n] = v
		}
		return ret(LoadoutMass(arg[string](a, 0), loadout, arg[*float64](a, 2)))
	},
	"radioBands": func(a []json.RawMessage) (any, error) { return ret(RadioBands(arg[string](a, 0))) },
	"isValidFrequency": func(a []json.RawMessage) (any, error) {
		return ret(IsValidFrequency(arg[string](a, 0), arg[int](a, 1), arg[float64](a, 2)))
	},
	"weaponInfo":      func(a []json.RawMessage) (any, error) { return ret(WeaponInfo(arg[string](a, 0))) },
	"launchPlatforms": func(a []json.RawMessage) (any, error) { return ret(LaunchPlatforms(arg[string](a, 0))) },
	"modelToUnits":    func(a []json.RawMessage) (any, error) { return ModelToUnits(arg[string](a, 0)), nil },
	"unitDetection":   func(a []json.RawMessage) (any, error) { return ret(UnitDetectionOf(arg[string](a, 0))) },
	"tacanFrequency": func(a []json.RawMessage) (any, error) {
		channel, err := intArg(a, 0)
		if err != nil {
			return nil, err
		}
		return ret(TacanFrequency(channel, arg[string](a, 1), arg[string](a, 2)))
	},
	"tacanChannel": func(a []json.RawMessage) (any, error) {
		return ret(TacanChannel(arg[float64](a, 0), arg[string](a, 1)))
	},
	"isValidTacan": func(a []json.RawMessage) (any, error) {
		return IsValidTacan(arg[float64](a, 0), arg[string](a, 1)), nil
	},
	"navaidsFor": func(a []json.RawMessage) (any, error) {
		if runway := arg[*string](a, 1); runway != nil {
			return ret(NavaidsForRunway(arg[string](a, 0), *runway))
		}
		return ret(NavaidsFor(arg[string](a, 0)))
	},
	"runwayEnds": func(a []json.RawMessage) (any, error) { return ret(RunwayEnds(arg[string](a, 0))) },
	"bestRunway": func(a []json.RawMessage) (any, error) {
		return ret(BestRunway(arg[string](a, 0), arg[float64](a, 1), arg[float64](a, 2)))
	},
	"nearestAirbases": func(a []json.RawMessage) (any, error) {
		o := arg[struct {
			N          *int     `json:"n"`
			MinRunwayM *float64 `json:"minRunwayM"`
			Category   string   `json:"category"`
		}](a, 3)
		n := 5
		if o.N != nil {
			n = *o.N
		}
		return ret(NearestAirbases(arg[string](a, 0), arg[float64](a, 1), arg[float64](a, 2), n,
			NearestOptions{MinRunwayM: o.MinRunwayM, Category: o.Category}))
	},
	"standsFor": func(a []json.RawMessage) (any, error) {
		return ret(StandsFor(arg[string](a, 0), arg[string](a, 1)))
	},
	"countryId": func(a []json.RawMessage) (any, error) {
		if id, ok := CountryIDOf(arg[string](a, 0)); ok {
			return id, nil
		}
		return nil, nil
	},
	"countryName": func(a []json.RawMessage) (any, error) { return ret(CountryName(arg[int](a, 0))) },
	"liveriesFor": func(a []json.RawMessage) (any, error) {
		if country := arg[*int](a, 1); country != nil {
			return ret(LiveriesForCountry(arg[string](a, 0), *country))
		}
		return ret(LiveriesFor(arg[string](a, 0)))
	},
	"datalinkCapability": func(a []json.RawMessage) (any, error) {
		return ret(DatalinkCapability(arg[string](a, 0)))
	},
	"distanceBearing": func(a []json.RawMessage) (any, error) {
		return ret(DistanceBearing(arg[float64](a, 0), arg[float64](a, 1), arg[float64](a, 2), arg[float64](a, 3)))
	},
	"destination": func(a []json.RawMessage) (any, error) {
		return ret(Destination(arg[float64](a, 0), arg[float64](a, 1), arg[float64](a, 2), arg[float64](a, 3)))
	},
	"formatCoord": func(a []json.RawMessage) (any, error) {
		lat, lon, format := arg[float64](a, 0), arg[float64](a, 1), arg[CoordFormat](a, 2)
		if precision := arg[*int](a, 3); precision != nil {
			return ret(FormatCoordPrecision(lat, lon, format, *precision))
		}
		return ret(FormatCoord(lat, lon, format))
	},
	"parseCoord": func(a []json.RawMessage) (any, error) { return ret(ParseCoord(arg[string](a, 0))) },
}

// intArg is argument i as an int; an error for a number with a fraction,
// which a Go int parameter cannot take (the vector must then expect one).
func intArg(args []json.RawMessage, i int) (int, error) {
	v := arg[float64](args, i)
	if v != math.Trunc(v) {
		return 0, fmt.Errorf("argument %d: %v is not an integer", i, v)
	}
	return int(v), nil
}

// generic is v as encoding/json decodes it into an any.
func generic(v any) (any, error) {
	b, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	var out any
	return out, json.Unmarshal(b, &out)
}

// closeTo compares as the Python runner does: numbers within abs + rel*|want|,
// strings, booleans and null exactly, arrays by position, objects by key set.
func closeTo(got, want any, abs, rel float64, path string) error {
	switch w := want.(type) {
	case float64:
		g, ok := got.(float64)
		if !ok || math.Abs(g-w) > abs+rel*math.Abs(w) {
			return fmt.Errorf("%s: got %v, want %v", path, got, w)
		}
	case []any:
		g, ok := got.([]any)
		if !ok || len(g) != len(w) {
			return fmt.Errorf("%s: got %v, want %v", path, got, w)
		}
		for i := range w {
			if err := closeTo(g[i], w[i], abs, rel, fmt.Sprintf("%s[%d]", path, i)); err != nil {
				return err
			}
		}
	case map[string]any:
		g, ok := got.(map[string]any)
		if !ok || len(g) != len(w) {
			return fmt.Errorf("%s: got %v, want %v", path, got, w)
		}
		for k, wv := range w {
			gv, ok := g[k]
			if !ok {
				return fmt.Errorf("%s: missing key %q in %v", path, k, got)
			}
			if err := closeTo(gv, wv, abs, rel, path+"."+k); err != nil {
				return err
			}
		}
	default:
		if got != want {
			return fmt.Errorf("%s: got %v, want %v", path, got, want)
		}
	}
	return nil
}

func TestConformanceVectors(t *testing.T) {
	b, err := os.ReadFile(vectorFile())
	if os.IsNotExist(err) {
		t.Skipf("no conformance vectors at %s", vectorFile())
	}
	if err != nil {
		t.Fatal(err)
	}
	var doc vectorDoc
	if err := json.Unmarshal(b, &doc); err != nil {
		t.Fatalf("%s: %v", vectorFile(), err)
	}
	if doc.DCSVersion != DCSVersion {
		t.Fatalf("vectors are of DCS %s, the data of %s", doc.DCSVersion, DCSVersion)
	}
	ran := map[string]int{}
	for i, c := range doc.Cases {
		run, ok := vectorHelpers[c.Fn]
		if !ok {
			t.Fatalf("case %d: no Go helper for vector function %s", i, c.Fn)
		}
		ran[c.Fn]++
		name := fmt.Sprintf("case %d %s%s", i, c.Fn, c.Args)
		got, err := run(c.Args)
		if c.Throws {
			if err == nil {
				t.Errorf("%s: want an error, got %v", name, got)
			}
			continue
		}
		if err != nil {
			t.Errorf("%s: %v", name, err)
			continue
		}
		var want any
		if err := json.Unmarshal(c.Expect, &want); err != nil {
			t.Fatalf("%s: unreadable expect %s", name, c.Expect)
		}
		g, err := generic(got)
		if err != nil {
			t.Fatal(err)
		}
		if err := closeTo(g, want, doc.Tolerance.Abs, doc.Tolerance.Rel, "$"); err != nil {
			t.Errorf("%s: %v", name, err)
		}
	}
	for fn := range vectorHelpers {
		if ran[fn] == 0 {
			t.Errorf("no vectors for %s", fn)
		}
	}
	total := 0
	for _, n := range ran {
		total += n
	}
	t.Logf("%d of %d vectors run", total, len(doc.Cases))
}
