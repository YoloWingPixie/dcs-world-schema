_G["db"]["Units"]["Helicopters"]["Helicopter"]["#Index"] = {
	AmmoWeight = 0,
	DisplayName = "Mi-8MTV2",
	EmptyWeight = "8866",
	IR_emission_coeff = 0.6,
	M_empty = 8866.2,
	M_fuel_max = 1929,
	M_max = 13000,
	M_nominal = 11100,
	MaxFuelWeight = "1929",
	MaxTakeOffWeight = "13000",
	Name = "Mi-8MTV2",
	RCS = 12,
	SFM_Data = {
		engine = {
			Nmg = 72,
			Shutdown_Duration = 42,
			Startup_Duration = 55,
			type = "TurboShaft"
		}
	},
	V_max = 250,
	V_max_cruise = 225,
	attribute = { 1, 2, 6, "Redacted", "Attack helicopters", "Transport helicopters", "All", "NonAndLightArmoredUnits", "NonArmoredUnits", "Air", "Helicopters" },
	bigParkingRamp = true,
	blade_area = 4.63,
	chaff_flare_dispenser = { {
			dir = { 0, 0.052, -0.999 },
			pos = { -0.55, -0.32, -1.28 }
		}, {
			dir = { 0, 0.052, 0.999 },
			pos = { -0.55, -0.32, 1.28 }
		} },
	detection_range_max = 0,
	engine_data = {
		Nmg_Ready = 84,
		SFC_k = { 2.045e-07, -0.0006328, 0.803 },
		power_RPM_k = { -0.08639, 0.24277, 0.84175 },
		power_RPM_min = 9.1384,
		power_TH_k = { { 0, -230.8, 2245.6 }, { 0, -230.8, 2245.6 }, { 0, -325.4, 2628.9 }, { 0, -235.6, 1931.9 } },
		power_WEP = 1618,
		power_max = 1618,
		power_take_off = 1470,
		sound_name = ""
	},
	engines_count = 2,
	fuselage_area = 4.8,
	height = 4.908,
	length = 25.942,
	main_gear_pos = { -1.322, -2.37, 2.118 },
	nose_gear_pos = { 3.236, -2.55, 0 },
	passivCounterm = {
		CMDS_Edit = true,
		ChaffNoEdit = true,
		SingleChargeTotal = 128,
		chaff = {
			chargeSz = 0,
			default = 0,
			increment = 0
		},
		flare = {
			chargeSz = 1,
			default = 128,
			increment = 32
		}
	},
	radar_can_see_ground = false,
	rotor_MOI = 26000,
	rotor_RPM = -192,
	rotor_diameter = 21.33,
	rotor_height = 2.602,
	rotor_pos = { 0.206, 2.575, 0 },
	stores_number = 0,
	tail_fin_area = 1.38,
	tail_rotor_RPM = 1124,
	tail_stab_area = 1.47,
	thrust_correction = 0.8,
	type = "Mi-8MT",
}