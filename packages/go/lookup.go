package dcsref

import (
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"sync"
)

// Reference is a record referencing another: its series, id and the
// referencing field (path from the record, arrays as "[]").
type Reference struct {
	Series SeriesName `json:"series"`
	ID     string     `json:"id"`
	Path   string     `json:"path"`
}

type indexMeta struct {
	UnitSeries []SeriesName `json:"unitSeries"`
	References []SeriesName `json:"references"`
	Names      []SeriesName `json:"names"`
}

var (
	indexMu    sync.Mutex
	indexCache = map[string]any{}
)

// index decodes data/_index/<name>.json into a T once.
func index[T any](name string) T {
	indexMu.Lock()
	defer indexMu.Unlock()
	if v, ok := indexCache[name]; ok {
		return v.(T)
	}
	var v T
	if err := json.Unmarshal(readData("_index/"+name), &v); err != nil {
		panic(fmt.Sprintf("dcsref: decoding index %s: %v", name, err))
	}
	indexCache[name] = v
	return v
}

func meta() indexMeta { return index[indexMeta]("meta") }

func ids(name, key string) []string {
	return slices.Clone(index[map[string][]string](name)[key])
}

// NameKey is the key the name indexes use: trimmed of ASCII whitespace, ASCII
// letters lowercased.
func NameKey(name string) string {
	s := strings.Trim(name, " \t\n\r\f\v")
	b := []byte(s)
	for i, c := range b {
		if 'A' <= c && c <= 'Z' {
			b[i] = c + ('a' - 'A')
		}
	}
	return string(b)
}

// ReferencesTo returns every record referencing record id of series, by any
// cross-reference field.
func ReferencesTo(series SeriesName, id string) []Reference {
	if !slices.Contains(meta().References, series) {
		return nil
	}
	return slices.Clone(index[map[string][]Reference]("references_" + string(series))[id])
}

func idsOf(refs []Reference, series SeriesName) []string {
	var out []string
	for _, r := range refs {
		if r.Series == series {
			out = append(out, r.ID)
		}
	}
	slices.Sort(out)
	return slices.Compact(out)
}

// StoresDelivering returns the CLSIDs of the stores delivering weapon
// weaponID.
func StoresDelivering(weaponID string) []string {
	return idsOf(ReferencesTo(SeriesWeapons, weaponID), SeriesStores)
}

// AircraftCarrying returns the aircraft with a station accepting a store that
// delivers weapon weaponID.
func AircraftCarrying(weaponID string) []string {
	return ids("carriers", weaponID)
}

// ThreatsForUnit returns the threat systems (threats ids) the unit type
// unitID is or is a component of.
func ThreatsForUnit(unitID string) []string {
	var refs []Reference
	for _, s := range meta().UnitSeries {
		refs = append(refs, ReferencesTo(s, unitID)...)
	}
	return idsOf(refs, SeriesThreats)
}

// AirbaseByName returns the ids of the airbases named name
// (case-insensitive) in theatre (its id, case-insensitive), or in any theatre
// when theatre is "".
func AirbaseByName(name, theatre string) []string {
	key := NameKey(name)
	var out []string
	for t, names := range index[map[string]map[string][]string]("airbases_by_name") {
		if theatre == "" || NameKey(t) == NameKey(theatre) {
			out = append(out, names[key]...)
		}
	}
	slices.Sort(out)
	return slices.Compact(out)
}

// FindByName returns the ids of the series records whose displayName or name
// is name (case-insensitive).
func FindByName(series SeriesName, name string) []string {
	if !slices.Contains(meta().Names, series) {
		return nil
	}
	return ids("names_"+string(series), NameKey(name))
}
