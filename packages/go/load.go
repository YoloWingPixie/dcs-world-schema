package dcsref

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"strings"
	"sync"
	"time"
)

// SeriesName names a series: "aircraft", "weapons", ...
type SeriesName string

// The bundles are embedded gzip-compressed as data/<name>.json.gz.
const gzExt = ".gz"

// Data returns the embedded bundles as a file system: <series>.json,
// manifest.json and the indexes under _index/, for decoding into your own
// types. Files are decompressed as they are opened.
func Data() fs.FS {
	sub, err := fs.Sub(dataFS, "data")
	if err != nil {
		panic(err)
	}
	return gzFS{sub}
}

func gunzip(b []byte) ([]byte, error) {
	r, err := gzip.NewReader(bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	defer r.Close()
	return io.ReadAll(r)
}

// readData returns data/<name>.json, decompressed.
func readData(name string) []byte {
	b, err := dataFS.ReadFile("data/" + name + ".json" + gzExt)
	if err == nil {
		b, err = gunzip(b)
	}
	if err != nil {
		panic(fmt.Sprintf("dcsref: %s: %v", name, err))
	}
	return b
}

// onceJSON decodes data/<name>.json into a T on first call.
func onceJSON[T any](name string) func() T {
	return sync.OnceValue(func() T {
		var v T
		if err := json.Unmarshal(readData(name), &v); err != nil {
			panic(fmt.Sprintf("dcsref: decoding %s: %v", name, err))
		}
		return v
	})
}

// gzFS serves the files of an fs.FS holding <name>.gz as <name>, decompressed.
type gzFS struct{ fsys fs.FS }

func (g gzFS) Open(name string) (fs.File, error) {
	if !fs.ValidPath(name) {
		return nil, &fs.PathError{Op: "open", Path: name, Err: fs.ErrInvalid}
	}
	if b, err := fs.ReadFile(g.fsys, name+gzExt); err == nil {
		data, err := gunzip(b)
		if err != nil {
			return nil, &fs.PathError{Op: "open", Path: name, Err: err}
		}
		return &gzFile{Reader: bytes.NewReader(data), info: gzInfo{name: pathBase(name), size: int64(len(data))}}, nil
	}
	f, err := g.fsys.Open(name)
	if err != nil {
		return nil, err
	}
	if st, err := f.Stat(); err == nil && st.IsDir() {
		return &gzDir{File: f, g: g, dir: name}, nil
	}
	f.Close()
	return nil, &fs.PathError{Op: "open", Path: name, Err: fs.ErrNotExist}
}

func (g gzFS) ReadDir(name string) ([]fs.DirEntry, error) {
	entries, err := fs.ReadDir(g.fsys, name)
	if err != nil {
		return nil, err
	}
	out := make([]fs.DirEntry, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() {
			out = append(out, e)
		} else if n, ok := strings.CutSuffix(e.Name(), gzExt); ok {
			p := n
			if name != "." {
				p = name + "/" + n
			}
			out = append(out, gzEntry{g: g, name: n, path: p})
		}
	}
	return out, nil
}

func pathBase(name string) string {
	return name[strings.LastIndexByte(name, '/')+1:]
}

type gzFile struct {
	*bytes.Reader
	info gzInfo
}

func (f *gzFile) Stat() (fs.FileInfo, error) { return f.info, nil }
func (f *gzFile) Close() error               { return nil }

type gzInfo struct {
	name string
	size int64
}

func (i gzInfo) Name() string       { return i.name }
func (i gzInfo) Size() int64        { return i.size }
func (i gzInfo) Mode() fs.FileMode  { return 0o444 }
func (i gzInfo) ModTime() time.Time { return time.Time{} }
func (i gzInfo) IsDir() bool        { return false }
func (i gzInfo) Sys() any           { return nil }

type gzEntry struct {
	g          gzFS
	name, path string
}

func (e gzEntry) Name() string      { return e.name }
func (e gzEntry) IsDir() bool       { return false }
func (e gzEntry) Type() fs.FileMode { return 0 }
func (e gzEntry) Info() (fs.FileInfo, error) {
	return fs.Stat(e.g, e.path)
}

// gzDir lists a directory with the .gz suffixes removed.
type gzDir struct {
	fs.File
	g       gzFS
	dir     string
	entries []fs.DirEntry
	read    bool
}

func (d *gzDir) ReadDir(n int) ([]fs.DirEntry, error) {
	if !d.read {
		entries, err := d.g.ReadDir(d.dir)
		if err != nil {
			return nil, err
		}
		d.entries, d.read = entries, true
	}
	if n <= 0 {
		out := d.entries
		d.entries = nil
		return out, nil
	}
	if len(d.entries) == 0 {
		return nil, io.EOF
	}
	n = min(n, len(d.entries))
	out := d.entries[:n]
	d.entries = d.entries[n:]
	return out, nil
}
