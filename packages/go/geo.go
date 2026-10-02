package dcsref

// Geo maths: great-circle distance and bearing, destination points, and the
// DCS mission editor's coordinate formats (DD, DMS, DDM, MGRS) both ways.

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// DistanceBearingResult is a great-circle distance and initial bearing.
type DistanceBearingResult struct {
	DistM float64 `json:"distM"`
	// BearingDeg is the initial true bearing, [0, 360).
	BearingDeg float64 `json:"bearingDeg"`
}

func checkLatLon(lat, lon float64) error {
	if !(-90 <= lat && lat <= 90 && -180 <= lon && lon <= 180) {
		return invalid("latitude %v / longitude %v out of range", lat, lon)
	}
	return nil
}

func bearing360(deg float64) float64 {
	if deg < 0 {
		deg += 360
	}
	if deg >= 360 {
		deg -= 360
	}
	return deg
}

// DistanceBearing returns the great-circle distance (haversine) and initial
// bearing from point 1 to point 2 on a sphere of radius EarthRadiusM (within
// about 0.5 % of the WGS84 geodesic); bearing 0 for coincident points.
func DistanceBearing(lat1, lon1, lat2, lon2 float64) (DistanceBearingResult, error) {
	if err := checkLatLon(lat1, lon1); err != nil {
		return DistanceBearingResult{}, err
	}
	if err := checkLatLon(lat2, lon2); err != nil {
		return DistanceBearingResult{}, err
	}
	p1, p2 := lat1*degToRad, lat2*degToRad
	dp, dl := p2-p1, (lon2-lon1)*degToRad
	a := math.Pow(math.Sin(dp/2), 2) + math.Cos(p1)*math.Cos(p2)*math.Pow(math.Sin(dl/2), 2)
	dist := 2 * EarthRadiusM * math.Asin(math.Sqrt(math.Min(1, a)))
	theta := math.Atan2(
		math.Sin(dl)*math.Cos(p2),
		math.Cos(p1)*math.Sin(p2)-math.Sin(p1)*math.Cos(p2)*math.Cos(dl),
	)
	return DistanceBearingResult{DistM: dist, BearingDeg: bearing360(theta * radToDeg)}, nil
}

// Destination returns the point distM from (lat, lon) along initial true
// bearing bearingDeg on the sphere of DistanceBearing; longitude in
// [-180, 180).
func Destination(lat, lon, bearingDeg, distM float64) (LatLon, error) {
	if err := checkLatLon(lat, lon); err != nil {
		return LatLon{}, err
	}
	p := destination(lat, lon, bearingDeg, distM)
	return LatLon{Lat: p[1], Lon: p[0]}, nil
}

// CoordFormat is a coordinate format of FormatCoord and ParseCoord.
type CoordFormat string

const (
	CoordDD     CoordFormat = "DD"
	CoordDMS    CoordFormat = "DMS"
	CoordDDM    CoordFormat = "DDM"
	CoordMGRS   CoordFormat = "MGRS"
	CoordMetric CoordFormat = "METRIC"
)

// coordPrecision is format -> default and largest precision: decimals of the
// degrees, seconds or minutes; MGRS digits per easting/northing.
var coordPrecision = map[CoordFormat][2]int{
	CoordDD:   {6, 8},
	CoordDMS:  {0, 4},
	CoordDDM:  {3, 6},
	CoordMGRS: {5, 5},
}

func pad(n int64, width int) string {
	s := strconv.FormatInt(n, 10)
	if len(s) < width {
		s = strings.Repeat("0", width-len(s)) + s
	}
	return s
}

func pow10(n int) int64 {
	out := int64(1)
	for range n {
		out *= 10
	}
	return out
}

func angle(value float64, format CoordFormat, precision int, hemis string) string {
	unit := pow10(precision)
	scale := map[CoordFormat]int64{CoordDD: 1, CoordDDM: 60, CoordDMS: 3600}[format] * unit
	total := int64(math.Floor(math.Abs(value)*float64(scale) + 0.5))
	hemi := hemis[0]
	if value < 0 && total > 0 {
		hemi = hemis[1]
	}
	whole, frac := total/unit, total%unit
	tail := ""
	if precision > 0 {
		tail = "." + pad(frac, precision)
	}
	switch format {
	case CoordDD:
		return fmt.Sprintf("%c %d%s°", hemi, whole, tail)
	case CoordDDM:
		return fmt.Sprintf("%c %d°%s%s'", hemi, whole/60, pad(whole%60, 2), tail)
	}
	return fmt.Sprintf("%c %d°%s'%s%s\"", hemi, whole/3600, pad(whole/60%60, 2), pad(whole%60, 2), tail)
}

// UTM/MGRS (WGS84): the Transverse Mercator of the theatre projections with
// k0 0.9996, false easting 500 km and false northing 10000 km south of the
// equator.
const (
	utmK0     = 0.9996
	mgrsBands = "CDEFGHJKLMNPQRSTUVWX"
	mgrsRows  = "ABCDEFGHJKLMNPQRSTUV"
)

var mgrsColumns = [3]string{"ABCDEFGH", "JKLMNPQR", "STUVWXYZ"}

func utm(zone int, south bool) *MapProjection {
	p := &MapProjection{CentralMeridian: float64(zone*6 - 183), ScaleFactor: utmK0, FalseEasting: 500000}
	if south {
		p.FalseNorthing = 10000000
	}
	return p
}

func bandLat(band byte) (float64, float64) {
	south := -80 + 8*float64(strings.IndexByte(mgrsBands, band))
	if band == 'X' {
		return south, 84
	}
	return south, south + 8
}

// pyModInt is Python's integer %: the result has the sign of b.
func pyModInt(a, b int64) int64 {
	m := a % b
	if m != 0 && (m < 0) != (b < 0) {
		m += b
	}
	return m
}

func mgrs(lat, lon float64, precision int) (string, error) {
	if !(-80 <= lat && lat <= 84) {
		return "", invalid("MGRS covers latitudes -80 to 84 (UTM), got %v", lat)
	}
	zone := min(int(math.Floor((lon+180)/6))+1, 60)
	band := mgrsBands[min(int(math.Floor((lat+80)/8)), 19)]
	if band == 'V' && zone == 31 && lon >= 3 {
		zone = 32
	} else if band == 'X' && 0 <= lon && lon < 42 {
		switch {
		case lon < 9:
			zone = 31
		case lon < 21:
			zone = 33
		case lon < 33:
			zone = 35
		default:
			zone = 37
		}
	}
	n, e := toMap(utm(zone, lat < 0), lat, lon)
	col := int64(math.Floor(e / 100000))
	shift := int64(0)
	if zone%2 == 0 {
		shift = 5
	}
	row := pyModInt(int64(math.Floor(n/100000))+shift, 20)
	letters := fmt.Sprintf("%d %c %c%c", zone, band, mgrsColumns[(zone-1)%3][col-1], mgrsRows[row])
	if precision == 0 {
		return letters, nil
	}
	div := pow10(5 - precision)
	de := pyModInt(int64(math.Floor(e)), 100000) / div
	dn := pyModInt(int64(math.Floor(n)), 100000) / div
	return fmt.Sprintf("%s %s %s", letters, pad(de, precision), pad(dn, precision)), nil
}

// FormatCoord writes (lat, lon) in format at its default precision (DD 6,
// DMS 0, DDM 3, MGRS 5); see FormatCoordPrecision.
func FormatCoord(lat, lon float64, format CoordFormat) (string, error) {
	p, ok := coordPrecision[format]
	if !ok {
		return "", invalid("format must be one of DD, DMS, DDM, MGRS, got %q", format)
	}
	return FormatCoordPrecision(lat, lon, format, p[0])
}

// FormatCoordPrecision writes (lat, lon) as the DCS mission editor does,
// without the Label: prefix it copies: DMS N 29°32'03"   E 52°35'55"
// (precision decimals of the seconds, 0-4; 2 is its "Lat Long Precise"), DDM
// N 29°32.296'   E 52°35.179' (minutes' decimals, 0-6), DD N 29.534312°
// E 52.598839° (degrees' decimals, 0-8; not an editor format) and MGRS
// 39 R XN 54929 68251 (digits per easting/northing, 0-5, truncated as MGRS
// is). Values round half up; degrees are not padded.
func FormatCoordPrecision(lat, lon float64, format CoordFormat, precision int) (string, error) {
	p, ok := coordPrecision[format]
	if !ok {
		return "", invalid("format must be one of DD, DMS, DDM, MGRS, got %q", format)
	}
	if precision < 0 || precision > p[1] {
		return "", invalid("%s precision must be an integer 0-%d, got %d", format, p[1], precision)
	}
	if err := checkLatLon(lat, lon); err != nil {
		return "", err
	}
	if format == CoordMGRS {
		return mgrs(lat, lon, precision)
	}
	return angle(lat, format, precision, "NS") + "   " + angle(lon, format, precision, "EW"), nil
}

// ParsedCoord is a coordinate ParseCoord read: Lat/Lon, or X/Z (DCS map
// metres north/east) for METRIC.
type ParsedCoord struct {
	Format CoordFormat `json:"format"`
	Lat    *float64    `json:"lat,omitzero"`
	Lon    *float64    `json:"lon,omitzero"`
	X      *float64    `json:"x,omitzero"`
	Z      *float64    `json:"z,omitzero"`
}

func latLonCoord(format CoordFormat, lat, lon float64) ParsedCoord {
	return ParsedCoord{Format: format, Lat: &lat, Lon: &lon}
}

type coordToken struct {
	kind byte // 'n' number, 'w' word, 'm' mark
	text string
}

func isDigit(c byte) bool { return '0' <= c && c <= '9' }

// coordTokens splits text after its first colon into numbers (sign, digits,
// optional decimals), words (letters) and marks (* for the degree sign, ',
// "), upper-cased; blanks and commas separate.
func coordTokens(text string) ([]coordToken, error) {
	s := text
	if _, after, ok := strings.Cut(text, ":"); ok {
		s = after
	}
	s = strings.ReplaceAll(s, "°", "*")
	for i := range len(s) {
		if s[i] >= 0x80 {
			return nil, invalid("unexpected non-ASCII text in %q", text)
		}
	}
	s = strings.ToUpper(s)
	var out []coordToken
	for i := 0; i < len(s); {
		c := s[i]
		switch {
		case c == ' ' || c == '\t' || c == ',':
			i++
		case c == '*' || c == '\'' || c == '"':
			out = append(out, coordToken{'m', string(c)})
			i++
		case 'A' <= c && c <= 'Z':
			j := i
			for j < len(s) && 'A' <= s[j] && s[j] <= 'Z' {
				j++
			}
			out = append(out, coordToken{'w', s[i:j]})
			i = j
		case c == '+' || c == '-' || isDigit(c):
			j := i
			if !isDigit(c) {
				j++
			}
			k := j
			for k < len(s) && isDigit(s[k]) {
				k++
			}
			if k == j {
				return nil, invalid("bad number in %q", text)
			}
			if k < len(s) && s[k] == '.' {
				m := k + 1
				for m < len(s) && isDigit(s[m]) {
					m++
				}
				if m == k+1 {
					return nil, invalid("bad number in %q", text)
				}
				k = m
			}
			out = append(out, coordToken{'n', s[i:k]})
			i = k
		default:
			return nil, invalid("unexpected %q in %q", c, text)
		}
	}
	return out, nil
}

func allDigits(s string) bool {
	for i := range len(s) {
		if !isDigit(s[i]) {
			return false
		}
	}
	return true
}

func unsigned(t coordToken) bool { return t.kind == 'n' && allDigits(t.text) }

func number(s string) float64 {
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		panic(fmt.Sprintf("dcsref: tokenizer passed a bad number %q", s))
	}
	return v
}

func parseMGRS(tokens []coordToken, text string) (ParsedCoord, error) {
	zone, _ := strconv.Atoi(tokens[0].text)
	i, letters := 1, ""
	for i < len(tokens) && tokens[i].kind == 'w' {
		letters += tokens[i].text
		i++
	}
	rest := tokens[i:]
	restOK := true
	for _, t := range rest {
		restOK = restOK && unsigned(t)
	}
	if len(letters) != 3 || len(rest) > 2 || !restOK {
		return ParsedCoord{}, invalid("not an MGRS reference: %q", text)
	}
	var es, ns string
	switch len(rest) {
	case 2:
		es, ns = rest[0].text, rest[1].text
	case 1:
		half := len(rest[0].text) / 2
		es, ns = rest[0].text[:half], rest[0].text[half:]
	}
	if len(es) != len(ns) || len(es) > 5 {
		return ParsedCoord{}, invalid("MGRS easting and northing need 0-5 digits each: %q", text)
	}
	band, col, row := letters[0], letters[1], letters[2]
	columns := mgrsColumns[(zone-1)%3]
	if strings.IndexByte(mgrsBands, band) < 0 || strings.IndexByte(columns, col) < 0 ||
		strings.IndexByte(mgrsRows, row) < 0 {
		return ParsedCoord{}, invalid("bad MGRS letters %s for zone %d: %q", letters, zone, text)
	}
	digits := func(s string) float64 {
		if s == "" {
			return 0
		}
		return number(s)
	}
	size := float64(pow10(5 - len(es)))
	e := float64(strings.IndexByte(columns, col)+1)*100000 + (digits(es)+0.5)*size
	shift := int64(0)
	if zone%2 == 0 {
		shift = 5
	}
	n := float64(pyModInt(int64(strings.IndexByte(mgrsRows, row))-shift, 20))*100000 + (digits(ns)+0.5)*size
	lo, hi := bandLat(band)
	p := utm(zone, lo < 0)
	mid, _ := toMap(p, (lo+hi)/2, p.CentralMeridian)
	n += math.Floor((mid-n)/2000000+0.5) * 2000000
	ll, err := inverse(p, n, e)
	if err != nil {
		return ParsedCoord{}, err
	}
	if !(lo-0.5 <= ll.Lat && ll.Lat <= hi+0.5) {
		return ParsedCoord{}, invalid("MGRS square %c%c is not in band %c: %q", col, row, band, text)
	}
	return latLonCoord(CoordMGRS, ll.Lat, ll.Lon), nil
}

// parseHalf reads H d [m [s]] from tokens[i]: signed degrees, component
// count and the next index.
func parseHalf(tokens []coordToken, i int, hemis, text string) (float64, int, int, error) {
	if i >= len(tokens) || tokens[i].kind != 'w' || (tokens[i].text != hemis[:1] && tokens[i].text != hemis[1:]) {
		return 0, 0, 0, invalid("expected %c or %c in %q", hemis[0], hemis[1], text)
	}
	sign := 1.0
	if tokens[i].text == hemis[1:] {
		sign = -1
	}
	i++
	var parts []string
	for i < len(tokens) && tokens[i].kind == 'n' && len(parts) < 3 {
		if !allDigits(strings.Replace(tokens[i].text, ".", "", 1)) {
			return 0, 0, 0, invalid("signed angle component in %q", text)
		}
		parts = append(parts, tokens[i].text)
		i++
		if i < len(tokens) && tokens[i].kind == 'm' {
			if tokens[i].text != string("*'\""[len(parts)-1]) {
				return 0, 0, 0, invalid("misplaced %s in %q", tokens[i].text, text)
			}
			i++
		}
	}
	if len(parts) == 0 {
		return 0, 0, 0, invalid("no angle after %c/%c in %q", hemis[0], hemis[1], text)
	}
	for _, p := range parts[:len(parts)-1] {
		if strings.Contains(p, ".") {
			return 0, 0, 0, invalid("only the last component may have decimals: %q", text)
		}
	}
	values := make([]float64, len(parts))
	for k, p := range parts {
		values[k] = number(p)
		if k > 0 && values[k] >= 60 {
			return 0, 0, 0, invalid("minutes and seconds must be below 60: %q", text)
		}
	}
	deg := values[0]
	if len(values) > 1 {
		deg += values[1] / 60
	}
	if len(values) > 2 {
		deg += values[2] / 3600
	}
	return sign * deg, len(parts), i, nil
}

// ParseCoord reads a coordinate in any DCS mission editor copy format, with
// or without its Label: prefix (the text up to the first colon is dropped):
// Metric: X+00380826 Z-00352108 (METRIC, map metres X/Z), N 29°32'03"
// E 52°35'55" and N 29°32'03.53"   E 52°35'55.82" (DMS), N 29°32.296'
// E 52°35.179' (DDM), 39 R XN 54929 68251 (MGRS: the centre of the square,
// so formatting it again at the same precision gives the same text), and
// N 29.5343°   E 52.5988° or a signed 29.5343, 52.5988 (DD). Case, spacing
// and the ° ' " marks are loose; anything else is an ErrInvalid error.
func ParseCoord(text string) (ParsedCoord, error) {
	tokens, err := coordTokens(text)
	if err != nil {
		return ParsedCoord{}, err
	}
	kinds := make([]byte, len(tokens))
	for i, t := range tokens {
		kinds[i] = t.kind
	}
	if string(kinds) == "wnwn" && tokens[0].text == "X" && tokens[2].text == "Z" {
		x, z := number(tokens[1].text), number(tokens[3].text)
		return ParsedCoord{Format: CoordMetric, X: &x, Z: &z}, nil
	}
	if len(kinds) >= 2 && string(kinds[:2]) == "nw" && unsigned(tokens[0]) && len(tokens[0].text) <= 2 {
		if zone, _ := strconv.Atoi(tokens[0].text); 1 <= zone && zone <= 60 {
			return parseMGRS(tokens, text)
		}
	}
	var lat, lon float64
	format := CoordDD
	if string(kinds) == "nn" {
		lat, lon = number(tokens[0].text), number(tokens[1].text)
	} else {
		var nLat, nLon, i int
		if lat, nLat, i, err = parseHalf(tokens, 0, "NS", text); err != nil {
			return ParsedCoord{}, err
		}
		if lon, nLon, i, err = parseHalf(tokens, i, "EW", text); err != nil {
			return ParsedCoord{}, err
		}
		if i != len(tokens) || nLat != nLon {
			return ParsedCoord{}, invalid("latitude and longitude need the same form: %q", text)
		}
		format = [4]CoordFormat{"", CoordDD, CoordDDM, CoordDMS}[nLat]
	}
	if err := checkLatLon(lat, lon); err != nil {
		return ParsedCoord{}, err
	}
	return latLonCoord(format, lat, lon), nil
}
