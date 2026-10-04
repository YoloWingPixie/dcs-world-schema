_G["weapons_table"]["weapons"]["missiles"]["TEST_AAM"] = __dcs{kind="anchor", id=1, value={
	actuator = {
		fins = __dcs{kind="anchor", id=2, value={ 0.3490658503988659, 0.30000000000000004 }},
		max_delta = 0.3490658503988659
	},
	controller = {
		big = 9007199254740992,
		boost_start = 0.5,
		owner = __dcs{kind="ref", id=1},
		tiny = 1e-300
	},
	display_name = "Test AAM",
	empty = {},
	flag = false,
	fm = {
		I = 58.6879125,
		caliber = 0.127,
		cx_coeff = { 1, 0.39, 0.38, 0.236, 1.31 },
		fins = __dcs{kind="ref", id=2},
		mass = 85.5
	},
	get_mass = __dcs{kind="function"},
	mixed = { "x", "y",
		[2.5] = "half",
		[true] = "yes",
		mode = "z"
	},
	modes = {
		index = 3
	},
	name = "TEST_AAM",
	negzero = __dcs{kind="number", value="-0"},
	shape_table_data = { {
			file = "test_aam",
			index = __dcs{kind="redacted", reason="patch-volatile", lua_type="number"},
			life = 1,
			name = "test_aam"
		} },
	sparse = { "a",
		[3] = "c",
		[10] = "j"
	},
	warhead = "_G/warheads/TEST_WH.lua",
	ws_type = { 4, 4, 7, "TEST_AAM" },
	zero = 0
}}