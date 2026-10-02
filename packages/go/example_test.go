package dcsref_test

import (
	"fmt"
	"slices"

	dcsref "github.com/YoloWingPixie/dcs-world-schema/packages/go"
)

// Which aircraft can carry the AIM-120C, and on which stores.
func Example() {
	aircraft := dcsref.LoadAircraft()
	carriers := dcsref.AircraftCarrying("AIM_120C")
	fmt.Println(slices.Contains(carriers, "FA-18C_hornet"), aircraft["FA-18C_hornet"].DisplayName)
	fmt.Println(len(dcsref.StoresDelivering("AIM_120C")) > 0)
	// Output:
	// true F/A-18C Lot 20
	// true
}
