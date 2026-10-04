_G["db"]["Units"]["Planes"]["Plane"]["#Index"] = {
	AmmoWeight = 147,
	DisplayName = "Su-27",
	EmptyWeight = "17250",
	IR_emission_coeff = 1,
	IR_emission_coeff_ab = 5,
	M_empty = 17250,
	M_fuel_max = 9400,
	M_max = 28000,
	M_nominal = 20000,
	MaxFuelWeight = "9400",
	MaxTakeOffWeight = "33000",
	Name = "Su-27",
	RCS = 5.5,
	SFM_Data = {
		aerodynamics = {
			Cy0 = 0,
			Czbe = -0.016,
			Mzalfa = 4.355,
			Mzalfadt = 0.8,
			cx_brk = 0.06,
			cx_flap = 0.063,
			cx_gear = 0.0268,
			cy_flap = 0.42,
			kjx = 2.7,
			kjz = 0.00125,
			table_data = { { 0, 0.0165, 0.077, 0.1, 0.032, 0.65, 25, 1.6 }, { 0.2, 0.0165, 0.077, 0.1, 0.032, 1.95, 25, 1.6 }, { 0.4, 0.0165, 0.077, 0.1, 0.032, 3.25, 25, 1.6 }, { 0.6, 0.0165, 0.08, 0.094, 0.043, 4.55, 24, 1.5 }, { 0.7, 0.017, 0.083, 0.094, 0.045, 4.55, 23, 1.45 }, { 0.8, 0.0178, 0.087, 0.094, 0.048, 4.55, 21, 1.4 }, { 0.9, 0.0215, 0.091, 0.11, 0.05, 4.55, 20, 1.3 }, { 1, 0.031, 0.094, 0.15, 0.1, 4.55, 18, 1.2 }, { 1.1, 0.0422, 0.094, 0.15, 0.1, 4.1, 16, 1.1 }, { 1.2, 0.044, 0.091, 0.14, 0.1, 3.19, 17, 1.05 }, { 1.3, 0.0432, 0.085, 0.17, 0.096, 2.28, 15, 1 }, { 1.5, 0.0423, 0.068, 0.23, 0.09, 1.95, 13, 0.9 }, { 1.8, 0.0416, 0.051, 0.23, 0.38, 1.17, 12, 0.7 }, { 2, 0.0416, 0.043, 0.08, 2.5, 1.04, 10.5, 0.55 }, { 2.2, 0.0416, 0.037, 0.16, 3.2, 0.91, 9, 0.4 }, { 2.5, 0.041, 0.036, 0.25, 4.5, 0.91, 9, 0.4 }, { 3.9, 0.0395, 0.033, 0.35, 6, 0.8, 9, 0.4 } }
		},
		engine = {
			ForsRUD = 0.91,
			MaksRUD = 0.85,
			MaxRUD = 1,
			MinRUD = 0,
			Nmg = 70.00001,
			cefor = 2.56,
			cemax = 1.24,
			dcx_eng = 0.0124,
			dpdh_f = 17000,
			dpdh_m = 8000,
			hMaxEng = 19.5,
			table_data = { { 0, 126000, 185024 }, { 0.2, 126000, 198744 }, { 0.4, 126000, 208250 }, { 0.6, 126000, 220892 }, { 0.7, 124000, 226870 }, { 0.8, 124000, 232887 }, { 0.9, 122000, 250210 }, { 1, 117000, 256120 }, { 1.1, 113000, 265400 }, { 1.2, 110000, 280300 }, { 1.3, 102000, 298900 }, { 1.5, 85000, 326000 }, { 1.8, 30000, 350000 }, { 2, 19000, 363000 }, { 2.2, 17000, 384000 }, { 2.5, 12000, 415000 }, { 3.9, 10000, 260476 } },
			type = "TurboJet"
		}
	},
	Sensors = {
		IRST = "OLS-27",
		RADAR = "N-001",
		RWR = "Abstract RWR"
	},
	WingSpan = "14.7",
	attribute = { 1, 1, 1, "Redacted", "Fighters", "All", "NonAndLightArmoredUnits", "NonArmoredUnits", "Air", "Planes", "Battle airplanes" },
	bigParkingRamp = false,
	chaff_flare_dispenser = { {
			dir = { 0, 1, 0 },
			pos = { -5.776, 1.4, -0.422 }
		}, {
			dir = { 0, 1, 0 },
			pos = { -5.776, 1.4, 0.422 }
		} },
	detection_range_max = 250,
	engines_count = 2,
	height = 5.932,
	length = 21.935,
	main_gear_pos = { -0.537, -2.237, 2.168 },
	main_gear_wheel_diameter = 0.972,
	nose_gear_pos = { 5.221, -2.185, 0 },
	nose_gear_wheel_diameter = 0.754,
	passivCounterm = {
		CMDS_Edit = true,
		SingleChargeTotal = 192,
		chaff = {
			chargeSz = 1,
			default = 96,
			increment = 3
		},
		flare = {
			chargeSz = 1,
			default = 96,
			increment = 3
		}
	},
	radar_can_see_ground = true,
	stores_number = 10,
	type = "Su-27",
	wing_area = 62,
	wing_span = 14.7,
	wing_tip_pos = { -4.5, 0.4, 7.5 }
}