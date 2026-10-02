package dcsref

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/fs"
	"reflect"
	"slices"
	"testing"
	"testing/fstest"
)

func strictDecodeOne[T any](b []byte) (T, error) {
	var v T
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&v); err != nil {
		return v, err
	}
	if dec.More() {
		return v, fmt.Errorf("trailing data")
	}
	return v, nil
}

// strictDecode decodes a bundle with unknown fields rejected and checks that
// every record marshals back to the JSON it was decoded from, so the types
// neither drop nor invent fields. It returns the records as generic values.
func strictDecode[T any](b []byte) (map[string]any, error) {
	typed, err := strictDecodeOne[map[string]T](b)
	if err != nil {
		return nil, err
	}
	var raw map[string]any
	if err := json.Unmarshal(b, &raw); err != nil {
		return nil, err
	}
	for id, rec := range typed {
		out, err := json.Marshal(rec)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", id, err)
		}
		var back any
		if err := json.Unmarshal(out, &back); err != nil {
			return nil, fmt.Errorf("%s: %w", id, err)
		}
		if !reflect.DeepEqual(back, raw[id]) {
			return nil, fmt.Errorf("%s: does not round-trip:\n got %s", id, out)
		}
	}
	if len(typed) != len(raw) {
		return nil, fmt.Errorf("%d typed records, %d in the bundle", len(typed), len(raw))
	}
	return raw, nil
}

func TestEverySeriesDecodesStrictly(t *testing.T) {
	if len(strictSeries) != len(SeriesNames) {
		t.Fatalf("%d strict decoders for %d series", len(strictSeries), len(SeriesNames))
	}
	for _, name := range SeriesNames {
		t.Run(string(name), func(t *testing.T) {
			raw, err := strictSeries[name](readData(string(name)))
			if err != nil {
				t.Fatal(err)
			}
			if len(raw) == 0 {
				t.Fatal("no records")
			}
			key := SeriesKeys[name]
			for id, rec := range raw {
				if got := fmt.Sprint(rec.(map[string]any)[key]); got != id {
					t.Fatalf("record %s has %s %s", id, key, got)
				}
			}
			if n := seriesLen(name); n != len(raw) {
				t.Fatalf("loader returned %d records, bundle holds %d", n, len(raw))
			}
		})
	}
}

func TestManifest(t *testing.T) {
	m, err := strictManifest(readData("manifest"))
	if err != nil {
		t.Fatal(err)
	}
	if m.DCSVersion != DCSVersion || LoadManifest().DCSVersion != DCSVersion {
		t.Fatalf("manifest DCS version %q, DCSVersion %q", m.DCSVersion, DCSVersion)
	}
}

func TestIndexesDecodeStrictly(t *testing.T) {
	entries, err := dataFS.ReadDir("data/_index")
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) == 0 {
		t.Fatal("no indexes")
	}
	m := meta()
	if len(m.UnitSeries) == 0 || len(m.References) == 0 || len(m.Names) == 0 {
		t.Fatalf("incomplete index meta: %+v", m)
	}
	for _, s := range m.References {
		if _, err := strictDecodeOne[map[string][]Reference](readData("_index/references_" + string(s))); err != nil {
			t.Fatalf("references_%s: %v", s, err)
		}
	}
}

func TestNameKey(t *testing.T) {
	for in, want := range map[string]string{
		"  Batumi\t": "batumi",
		"F-16C_50":   "f-16c_50",
		"ÄBC":        "Äbc",
		"":           "",
	} {
		if got := NameKey(in); got != want {
			t.Errorf("NameKey(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestReferencesToMatchesIndex(t *testing.T) {
	m := meta()
	for _, target := range m.References {
		idx := index[map[string][]Reference]("references_" + string(target))
		for id, want := range idx {
			if got := ReferencesTo(target, id); !reflect.DeepEqual(got, want) {
				t.Fatalf("ReferencesTo(%s, %s) = %v, want %v", target, id, got, want)
			}
		}
	}
	if got := ReferencesTo("no_such_series", "x"); got != nil {
		t.Fatalf("unknown series: %v", got)
	}
}

func TestAircraftCarryingMatchesIndex(t *testing.T) {
	idx := index[map[string][]string]("carriers")
	if len(idx) == 0 {
		t.Fatal("empty carriers index")
	}
	aircraft := LoadAircraft()
	for weapon, want := range idx {
		got := AircraftCarrying(weapon)
		if !slices.Equal(got, want) {
			t.Fatalf("AircraftCarrying(%s) = %v, want %v", weapon, got, want)
		}
		for _, a := range got {
			if _, ok := aircraft[a]; !ok {
				t.Fatalf("AircraftCarrying(%s): unknown aircraft %s", weapon, a)
			}
		}
	}
}

func TestStoresDeliveringMatchesData(t *testing.T) {
	// Brute force over the typed stores: every delivery's weapon.
	want := map[string][]string{}
	for clsid, s := range LoadStores() {
		for _, d := range s.Delivers {
			if d.Weapon != "" {
				want[d.Weapon] = append(want[d.Weapon], clsid)
			}
		}
	}
	weapons := LoadWeapons()
	checked := 0
	for weapon, stores := range want {
		if _, ok := weapons[weapon]; !ok {
			continue // unresolved reference: not indexed
		}
		slices.Sort(stores)
		if got := StoresDelivering(weapon); !slices.Equal(got, slices.Compact(stores)) {
			t.Fatalf("StoresDelivering(%s) = %v, want %v", weapon, got, stores)
		}
		checked++
	}
	if checked == 0 {
		t.Fatal("no weapon delivered by a store")
	}
}

func TestThreatsForUnitMatchesData(t *testing.T) {
	units := map[string]bool{}
	for _, s := range []SeriesName{SeriesAircraft, SeriesGroundVehicles, SeriesPersonnel, SeriesShips, SeriesStructures} {
		for id := range readRaw(t, s) {
			units[id] = true
		}
	}
	want := map[string][]string{}
	for id, th := range LoadThreats() {
		add := func(u string) {
			if units[u] {
				want[u] = append(want[u], id)
			}
		}
		if th.Unit != nil {
			add(*th.Unit)
		}
		for _, c := range th.Components {
			add(c.Unit)
		}
	}
	if len(want) == 0 {
		t.Fatal("no threat units")
	}
	for unit, threats := range want {
		slices.Sort(threats)
		if got := ThreatsForUnit(unit); !slices.Equal(got, slices.Compact(threats)) {
			t.Fatalf("ThreatsForUnit(%s) = %v, want %v", unit, got, threats)
		}
	}
}

func TestAirbaseByNameMatchesIndex(t *testing.T) {
	idx := index[map[string]map[string][]string]("airbases_by_name")
	if len(idx) == 0 {
		t.Fatal("empty airbases_by_name index")
	}
	airbases := LoadAirbases()
	for theatre, names := range idx {
		for key, want := range names {
			if got := AirbaseByName(key, theatre); !slices.Equal(got, want) {
				t.Fatalf("AirbaseByName(%q, %q) = %v, want %v", key, theatre, got, want)
			}
			for _, id := range want {
				ab := airbases[id]
				if ab.Name == nil || NameKey(*ab.Name) != key || ab.Theatre != theatre {
					t.Fatalf("airbase %s is not %q in %s", id, key, theatre)
				}
				if !slices.Contains(AirbaseByName(" "+*ab.Name+" ", ""), id) {
					t.Fatalf("AirbaseByName(%q, any) misses %s", *ab.Name, id)
				}
			}
		}
	}
}

func TestFindByNameMatchesData(t *testing.T) {
	for _, s := range meta().Names {
		want := map[string][]string{}
		for id, rec := range readRaw(t, s) {
			for _, f := range []string{"displayName", "name"} {
				if v, ok := rec[f].(string); ok && NameKey(v) != "" {
					want[NameKey(v)] = append(want[NameKey(v)], id)
				}
			}
		}
		idx := index[map[string][]string]("names_" + string(s))
		if len(idx) != len(want) {
			t.Fatalf("%s: %d name keys indexed, %d in the data", s, len(idx), len(want))
		}
		for key, ids := range want {
			slices.Sort(ids)
			ids = slices.Compact(ids)
			if got := FindByName(s, key); !slices.Equal(got, ids) {
				t.Fatalf("FindByName(%s, %q) = %v, want %v", s, key, got, ids)
			}
			if !slices.Equal(idx[key], ids) {
				t.Fatalf("names_%s[%q] = %v, want %v", s, key, idx[key], ids)
			}
		}
	}
}

func readRaw(t *testing.T, s SeriesName) map[string]map[string]any {
	t.Helper()
	var raw map[string]map[string]any
	if err := json.Unmarshal(readData(string(s)), &raw); err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestDataServesDecompressedJSON(t *testing.T) {
	if err := fstest.TestFS(Data(), "manifest.json", "aircraft.json", "_index/meta.json"); err != nil {
		t.Fatal(err)
	}
	b, err := fs.ReadFile(Data(), "manifest.json")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(b, readData("manifest")) || !json.Valid(b) {
		t.Fatal("Data() manifest.json is not the decompressed bundle")
	}
}
