package dcsref

// The tagged union types (BoolOrNumber, Scalar, ...) are generated into
// types_gen.go by tools/package/go_package.py, one per set of JSON kinds a
// record field mixes.

// Truthy reports the value as a flag: true, or a non-zero number.
func (v BoolOrNumber) Truthy() bool {
	if v.Bool != nil {
		return *v.Bool
	}
	return v.Number != nil && *v.Number != 0
}
