package dcsref

import (
	"encoding/json"
	"testing"
)

func TestUnionsRejectOtherKinds(t *testing.T) {
	for _, tc := range []struct {
		name string
		into any
		bad  []string
	}{
		{"NumberOrString", new(NumberOrString), []string{"true", "false", "null", "{}", "[]"}},
		{"BoolOrNumber", new(BoolOrNumber), []string{`"1"`, "null", "{}", "[]"}},
		{"Scalar", new(Scalar), []string{"null", "{}", "[1]", "tru"}},
	} {
		for _, in := range tc.bad {
			if err := json.Unmarshal([]byte(in), tc.into); err == nil {
				t.Errorf("%s accepted %s", tc.name, in)
			}
		}
	}
}

func TestUnionsRoundTrip(t *testing.T) {
	check := func(name string, into any, in string) {
		t.Helper()
		if err := json.Unmarshal([]byte(in), into); err != nil {
			t.Fatalf("%s rejected %s: %v", name, in, err)
		}
		out, err := json.Marshal(into)
		if err != nil {
			t.Fatalf("%s: marshal %s: %v", name, in, err)
		}
		if string(out) != in {
			t.Errorf("%s: %s round-tripped to %s", name, in, out)
		}
	}
	for _, in := range []string{"1.5", "-2", `"a"`} {
		check("NumberOrString", new(NumberOrString), in)
	}
	for _, in := range []string{"true", "false", "0", "3"} {
		check("BoolOrNumber", new(BoolOrNumber), in)
	}
	for _, in := range []string{"true", "7", `"x"`} {
		check("Scalar", new(Scalar), in)
	}
}

func TestUnionSetsOneMember(t *testing.T) {
	var v NumberOrString
	if err := json.Unmarshal([]byte(`"7"`), &v); err != nil {
		t.Fatal(err)
	}
	if v.String == nil || *v.String != "7" || v.Number != nil {
		t.Errorf("got %+v, want only String", v)
	}
	var b BoolOrNumber
	if err := json.Unmarshal([]byte("2"), &b); err != nil || !b.Truthy() || b.Bool != nil {
		t.Errorf("got %+v (%v), want only Number 2", b, err)
	}
}
