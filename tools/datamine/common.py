"""Shared helpers for the datamine tools: repo paths, the series registry, DCS
version handling, deterministic JSON I/O, Lua file walks and the I/O pool."""

from __future__ import annotations

import enum
import functools
import hashlib
import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = REPO_ROOT / "dist"
SPEC_PATH = DIST_DIR / "dcs-world-api-schema.json"
JSON_SCHEMA_PATH = DIST_DIR / "dcs-world-entities.schema.json"
REFERENCE_DATA_DIR = REPO_ROOT / "dcs-world-reference"
CACHE_DIR = REPO_ROOT / ".datamine"
CACHED_G_DIR = CACHE_DIR / "_G"
MANIFEST = "manifest.json"
LATEST = "latest"  # the newest DCS version's data; older ones are in git history
API_DIR = "api"  # the Lua API dumps (api_dump); not a series

VERSION_MARKER = "__DCS_VERSION__.lua"
_VERSION_TOKEN = re.compile(r"^[0-9]+(?:\.[0-9]+){2,}$")
HOOK_DIR = Path(__file__).resolve().parent / "hook"
DUMP_HOOK = HOOK_DIR / "dump-globals.lua"
_DUMP_HOOK_TEXT = DUMP_HOOK.read_text(encoding="utf-8")
# The dump hook's format (its DUMP_FORMAT, in __DUMP_FORMAT__.lua) and the
# tables it writes whole, one file each (its WRITE_WHOLE, dotted _G paths).
FORMAT_MARKER = "__DUMP_FORMAT__.lua"


def _hook_constant(pattern: str, flags: int) -> str:
    """Group 1 of ``pattern``'s match in the dump hook."""
    m = re.search(pattern, _DUMP_HOOK_TEXT, flags)
    if m is None:
        raise RuntimeError(f"{DUMP_HOOK} does not match {pattern!r}")
    return m[1]


DUMP_FORMAT = int(_hook_constant(r"^local DUMP_FORMAT = (\d+)$", re.M))
WRITE_WHOLE: tuple[str, ...] = tuple(
    re.findall(
        r"'([^']+)'",
        _hook_constant(r"^local WRITE_WHOLE = \{(.*?)^\}", re.M | re.S),
    )
)

# `_source` provenance values; an absent entry means datamined.
CORRECTED = "corrected"
HAND_AUTHORED = "hand-authored"


@dataclass(frozen=True)
class Series:
    name: str
    type_name: str
    id_field: str
    unit: bool = False  # a unit type (target of unit-type references)
    # Records under ``<record[f]>/`` per field ``f`` in turn, files named by
    # ``record[file_field]``.
    group_fields: tuple[str, ...] = ()
    file_field: str | None = None


SERIES: dict[str, Series] = {
    s.name: s
    for s in (
        Series("aircraft", "Entity.Aircraft", "id", unit=True),
        Series("ground_vehicles", "Entity.GroundVehicle", "id", unit=True),
        Series("personnel", "Entity.Personnel", "id", unit=True),
        Series("ships", "Entity.Ship", "id", unit=True),
        Series("structures", "Entity.Structure", "id", unit=True),
        Series("sensors", "Entity.Sensor", "id"),
        Series("radios", "Entity.Radio", "id"),
        Series("datalink", "Entity.Datalink", "id"),
        Series("weapons", "Entity.Weapon", "id"),
        Series("warheads", "Entity.Warhead", "id"),
        Series("weapon_flight", "Entity.WeaponFlight", "weapon"),
        Series("aircraft_flight", "Entity.AircraftFlight", "aircraft"),
        Series("stores", "Entity.Store", "clsid"),
        Series("racks", "Entity.Rack", "id"),
        Series("gun_ammo", "Entity.GunAmmo", "id"),
        Series("fuzes", "Entity.FuzeType", "id"),
        Series("attributes", "Entity.Attribute", "id"),
        Series("countries", "Entity.Country", "id"),
        Series("callsigns", "Entity.CountryCallsigns", "country"),
        Series("tasks", "Entity.Task", "id"),
        Series("skills", "Entity.Skill", "id"),
        Series("formations", "Entity.Formation", "id"),
        Series("actions", "Entity.Action", "id"),
        Series("options", "Entity.ActionOption", "id"),
        Series("threats", "Entity.ThreatSystem", "id"),
        Series("liveries", "Entity.Livery", "id"),
        Series("theatres", "Entity.Theatre", "id"),
        Series(
            "beacons",
            "Entity.Beacon",
            "id",
            group_fields=("theatre", "typeName"),
            file_field="beaconId",
        ),
        Series("navaids", "Entity.Navaid", "id"),
        Series(
            "airbases",
            "Entity.Airbase",
            "id",
            group_fields=("theatre",),
            file_field="name",
        ),
    )
}
UNIT_SERIES = [s.name for s in SERIES.values() if s.unit]
# The ``Entity.AttributeUnits`` field of each unit series.
UNIT_SERIES_KEYS = {
    s: re.sub(r"_(.)", lambda m: m.group(1).upper(), s) for s in UNIT_SERIES
}
MANIFEST_TYPE = "Entity.Provenance"
# Entity types with no extractor yet; kept in the spec as planned shapes.
UNEXTRACTED_TYPES: tuple[str, ...] = ()


_YAML_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_YAML_PLAIN_SPACED = re.compile(r"^[A-Za-z_]([A-Za-z0-9_ ]*[A-Za-z0-9_])?$")
# Plain scalars YAML 1.1 reads as booleans or null.
_YAML_WORDS = {"y", "n", "yes", "no", "on", "off", "true", "false", "null"}


def yaml_key(name: str, spaces: bool = False) -> str:
    """``name`` as a YAML mapping key: bare when it is an identifier (with inner
    ``spaces`` if allowed) that no YAML 1.1 reader takes for a boolean or null,
    else double-quoted."""
    plain = _YAML_PLAIN_SPACED if spaces else _YAML_PLAIN
    if plain.match(name) and name.lower() not in _YAML_WORDS:
        return name
    return json.dumps(name)


def fail(msg: str) -> NoReturn:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def read_version(g_dir: Path) -> str | None:
    """The DCS version in ``<g_dir>/__DCS_VERSION__.lua``, or None if the marker
    is absent. A marker that is not a bare dotted version is an error."""
    try:
        text = (g_dir / VERSION_MARKER).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    text = text.strip()
    if not _VERSION_TOKEN.match(text):
        fail(f"unparseable DCS version marker in {g_dir}: {text[:80]!r}")
    return text


def read_dump_format(g_dir: Path) -> int | None:
    """The dump format in ``<g_dir>/__DUMP_FORMAT__.lua``; None when absent. A
    marker that is not a bare integer is an error."""
    text = read_marker(g_dir / FORMAT_MARKER)
    if text is None:
        return None
    if not text.isdigit():
        fail(f"unparseable dump format marker in {g_dir}: {text[:80]!r}")
    return int(text)


def autoupdate_cfg(install_dir: Path) -> dict[str, Any]:
    """The install's ``autoupdate.cfg``; empty when absent or not a JSON object."""
    try:
        cfg = json.loads(read_text(install_dir / "autoupdate.cfg"))
    except (FileNotFoundError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def install_version(install_dir: Path) -> str | None:
    """The ``version`` in the install's ``autoupdate.cfg``; None when absent."""
    version = autoupdate_cfg(install_dir).get("version")
    return version if isinstance(version, str) else None


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in version.split("."))


def latest_version(data_root: Path) -> str | None:
    """The DCS version ``<data_root>/latest`` holds (its manifest's
    ``dcsVersion``); None when there is no ``latest``."""
    path = data_root / LATEST / MANIFEST
    if not path.is_file():
        return None
    version = load_json(path).get("dcsVersion")
    if not isinstance(version, str):
        fail(f"{path} names no dcsVersion")
    return version


def version_data(data_root: Path, version: str) -> Path | None:
    """``<data_root>/latest`` when it holds DCS ``version``, else None."""
    return data_root / LATEST if latest_version(data_root) == version else None


_WIN_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def to_wsl_path(p: str) -> Path:
    """A Windows path (``C:\\Users\\..``) as its WSL mount (``/mnt/c/Users/..``)."""
    m = _WIN_PATH.match(p)
    if m:
        return Path(f"/mnt/{m.group(1).lower()}/{m.group(2).replace(chr(92), '/')}")
    return Path(p)


# Characters no Windows, macOS or Linux file name may hold.
_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')
_TRAILING = re.compile(r"[. ]+$")  # Windows drops them from a folder name
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]) *(\.|$)", re.IGNORECASE)


def safe_name(name: str, folder: bool = False) -> str:
    """``name`` with every character a file name cannot hold replaced by ``_``
    (for a ``folder`` also trailing dots and spaces), and ``_`` prefixed to a
    Windows reserved device name."""
    safe = _UNSAFE.sub("_", name)
    if folder:
        safe = _TRAILING.sub(lambda m: "_" * len(m.group()), safe)
    return f"_{safe}" if _RESERVED.match(safe) else safe


def sanitize_id(
    entity_id: str,
    used: set[str],
    alternates: Iterable[str] = (),
    folder: bool = False,
) -> str:
    """A filesystem-safe, collision-free filename stem for an entity id.

    The record carries the true id; this is only a file handle, the id itself
    wherever the file system allows (``safe_name``). Only when that stem is empty or
    already in ``used`` is a short hash of the original id appended, then of each
    of ``alternates`` in turn while it still collides. Collisions are checked
    case-insensitively: Windows and macOS checkouts would otherwise merge ids
    that differ only in case into one file.
    """
    safe = safe_name(entity_id, folder)
    if not safe or safe.lower() in used:
        for source in (entity_id, *alternates):
            digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:8]
            candidate = f"{safe or 'id'}~{digest}"
            if candidate.lower() not in used:
                break
        else:
            fail(f"no collision-free file name for {entity_id!r}")
        safe = candidate
    used.add(safe.lower())
    return safe


@functools.cache
def _pool() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=32, thread_name_prefix="datamine-io")


def pmap[T, R](fn: Callable[[T], R], items: Iterable[T]) -> Iterator[R]:
    """``map`` on the shared I/O pool; results are yielded in order as they arrive."""
    return _pool().map(fn, items)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return cast(dict[str, Any], json.load(fh))


def json_text(payload: Any, compact: bool = False) -> str:
    """Deterministic JSON (sorted keys): indented, or ``compact`` on one line."""
    if compact:
        text = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    else:
        text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return text + "\n"


def write_bytes_if_changed(path: Path, data: bytes) -> bool:
    """Write ``data`` to ``path`` (parent dirs made as needed) unless the file
    already holds exactly it; whether it was written."""
    try:
        if path.read_bytes() == data:
            return False
    except FileNotFoundError:
        pass
    try:
        path.write_bytes(data)
    except FileNotFoundError:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return True


def write_text_if_changed(path: Path, text: str) -> bool:
    """``write_bytes_if_changed`` of ``text`` as UTF-8, newlines untranslated."""
    return write_bytes_if_changed(path, text.encode("utf-8"))


def series_files(series: Series, records: dict[str, Any]) -> dict[str, Any]:
    """``{relative path: record}``: ``<key>.json``, or for a grouped series
    ``<group>/.../<file_field>.json``, each part sanitised (``sanitize_id``).
    Folders are named in sorted order; in each folder, stems that need no
    sanitising are claimed first, then the rest, each in sorted key order."""
    groups = {
        k: tuple(str(records[k][f]) for f in series.group_fields) for k in records
    }
    folders: dict[tuple[str, ...], tuple[str, ...]] = {(): ()}
    used_dirs: dict[tuple[str, ...], set[str]] = {}
    for raw in sorted(set(groups.values())):
        for i in range(1, len(raw) + 1):
            if raw[:i] not in folders:
                parent = folders[raw[: i - 1]]
                used = used_dirs.setdefault(parent, set())
                folders[raw[:i]] = (*parent, sanitize_id(raw[i - 1], used, folder=True))

    def stem_source(k: str) -> str:
        name = records[k].get(series.file_field) if series.file_field else None
        return str(name or k)

    used_files: dict[tuple[str, ...], set[str]] = {}
    out: dict[str, Any] = {}
    for k in sorted(
        records, key=lambda k: (safe_name(stem_source(k)) != stem_source(k), k)
    ):
        folder = folders[groups[k]]
        used = used_files.setdefault(folder, set())
        stem = sanitize_id(stem_source(k), used, (str(k),))
        out["/".join((*folder, f"{stem}.json"))] = records[k]
    return dict(sorted(out.items()))


def sync_tree(directory: Path, files: dict[Path, bytes]) -> None:
    """Make ``directory`` hold exactly ``files``: write the changed ones and
    delete every other file and directory, so stale records cannot persist."""
    dirs = {directory}
    for parent in {path.parent for path in files}:
        while parent not in dirs:
            dirs.add(parent)
            parent = parent.parent
    for d in sorted(dirs):
        d.mkdir(parents=True, exist_ok=True)
    stale_files: list[Path] = []
    stale_dirs: list[Path] = []
    for root, subdirs, names in os.walk(directory):
        stale_files += [p for n in names if (p := Path(root, n)) not in files]
        stale_dirs += [p for n in subdirs if (p := Path(root, n)) not in dirs]
    list(pmap(os.remove, stale_files))
    for d in stale_dirs:
        shutil.rmtree(d, ignore_errors=True)
    list(pmap(lambda item: write_bytes_if_changed(*item), files.items()))


def series_bytes(series: Series, records: dict[str, Any]) -> dict[str, bytes]:
    """``series_files`` with each record as its JSON file's bytes."""
    return {
        rel: json_text(rec).encode("utf-8")
        for rel, rec in series_files(series, records).items()
    }


def tree_files(root: Path) -> dict[str, Path]:
    """Every file under ``root`` by its POSIX path relative to ``root``."""
    out: dict[str, Path] = {}
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            p = Path(dirpath, n)
            out[p.relative_to(root).as_posix()] = p
    return out


def read_tree(root: Path) -> dict[str, bytes]:
    """The bytes of every file under ``root`` by its POSIX relative path."""
    files = tree_files(root)
    return dict(zip(files, pmap(Path.read_bytes, files.values()), strict=True))


def series_records[T](tree: dict[str, T]) -> dict[str, dict[str, T]]:
    """``{series: {file stem: value}}`` of a data dir's ``{relative path:
    value}`` (bytes, paths, ...): the ``.json`` files at the depth each series
    puts its records (``series_files``). A top-level dir that is no series (nor
    ``API_DIR``) fails."""
    out: dict[str, dict[str, T]] = {}
    for rel, value in sorted(tree.items()):
        name, sep, sub = rel.partition("/")
        if not sep or name == API_DIR:
            continue
        series = SERIES.get(name)
        if series is None:
            fail(f"unmapped series directory: {name}")
        records = out.setdefault(name, {})
        if sub.endswith(".json") and sub.count("/") == len(series.group_fields):
            records[sub.removesuffix(".json")] = value
    return out


def write_latest(data_root: Path, files: dict[str, bytes]) -> Path:
    """Make ``<data_root>/latest`` hold exactly ``files`` (``{relative path:
    bytes}``, with a ``manifest.json``); the DCS version they are must not be
    older than the one ``latest`` holds. The ``latest`` dir."""
    if MANIFEST not in files:
        fail(f"no {MANIFEST} in the data written to {data_root / LATEST}")
    version = json.loads(files[MANIFEST])["dcsVersion"]
    current = latest_version(data_root)
    if current is not None and version_key(version) < version_key(current):
        fail(f"DCS {version} is older than {data_root / LATEST} (DCS {current})")
    latest = data_root / LATEST
    sync_tree(latest, {latest / rel: b for rel, b in files.items()})
    return latest


# A probe document (``api/probe.json``, ``api/actions-probe.json``) carried
# forward from an earlier version: the DCS version the probe ran on.
PROBED_ON = "probedOn"


def probed_on(doc: dict[str, Any]) -> str:
    """The DCS version a probe document's results were measured on."""
    return cast(str, doc.get(PROBED_ON) or doc["dcsVersion"])


def carry_forward(doc: dict[str, Any], version: str) -> dict[str, Any]:
    """Probe document ``doc`` as DCS ``version``'s: ``dcsVersion`` set to it,
    ``probedOn`` to the version the probe ran on."""
    return {**doc, "dcsVersion": version, PROBED_ON: probed_on(doc)}


def version_probe(data_root: Path, version: str, file: str) -> dict[str, Any] | None:
    """The probe document ``api/<file>`` for DCS ``version`` from
    ``<data_root>/latest``: its own when ``latest`` is ``version``, else (an
    older ``latest``, read before the new version replaces it) carried forward
    (``carry_forward``); None when there is none."""
    current = latest_version(data_root)
    if current is None or version_key(current) > version_key(version):
        return None
    path = data_root / LATEST / API_DIR / file
    if not path.is_file():
        return None
    doc = load_json(path)
    return doc if doc.get("dcsVersion") == version else carry_forward(doc, version)


def read_marker(path: Path) -> str | None:
    """A marker file's text, stripped; None when it is absent."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


def hooks_hash(paths: Iterable[Path]) -> str:
    """SHA-256 of hook files' names and contents."""
    h = hashlib.sha256()
    for path in paths:
        h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def glob_re(pattern: str) -> re.Pattern[str]:
    """A pattern whose ``*`` stands for any text, for ``fullmatch``."""
    return re.compile(".*".join(re.escape(p) for p in pattern.split("*")))


class CacheState(enum.Enum):
    """What a cached probe or dump holds for a DCS version and inputs."""

    MISSING = "missing"
    PARTIAL = "partial"  # this version and inputs, unfinished
    OTHER_VERSION = "other version"
    INPUTS_CHANGED = "inputs changed"
    CURRENT = "current"


DONE, PARTIAL, INPUTS = "done", "partial", "inputs"


@dataclass(frozen=True)
class ProbeCache:
    """A cached run in ``dir``: the document ``file``, the ``inputs_file``
    (what it was made from), then ``done`` (complete) or ``partial`` holding
    the DCS version. ``what`` and ``changed`` name it and its inputs in
    reasons."""

    dir: Path
    file: str
    what: str
    changed: str
    inputs_file: str = INPUTS

    def marker(self, name: str) -> str | None:
        return read_marker(self.dir / name)

    def status(self, version: str, inputs: str) -> tuple[CacheState, str]:
        """The cache's state for ``version`` and ``inputs``, and why."""
        done = self.marker(DONE)
        same = self.marker(self.inputs_file) == inputs
        if done is None:
            if self.marker(PARTIAL) == version and same:
                return CacheState.PARTIAL, f"cached {self.what} is partial"
            if self.marker(PARTIAL) == version:
                return CacheState.INPUTS_CHANGED, f"{self.changed} changed since it ran"
            return CacheState.MISSING, f"no cached {self.what}"
        if done != version:
            return CacheState.OTHER_VERSION, f"cached {self.what} is DCS {done}"
        if not same:
            return CacheState.INPUTS_CHANGED, f"{self.changed} changed since it ran"
        return CacheState.CURRENT, f"cached {self.what} is current"

    def stale(self, version: str, inputs: str) -> str | None:
        """Why the run must be redone, or None when the cache is current."""
        state, why = self.status(version, inputs)
        return None if state is CacheState.CURRENT else why

    def write(self, doc: dict[str, Any], version: str, inputs: str) -> None:
        """Cache ``doc``; ``done`` (``doc["stats"]["complete"]``) or
        ``partial``, written last, marks it as ``version``'s."""
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / DONE).unlink(missing_ok=True)
        (self.dir / PARTIAL).unlink(missing_ok=True)
        (self.dir / self.inputs_file).write_text(inputs, encoding="utf-8")
        (self.dir / self.file).write_text(json_text(doc), encoding="utf-8")
        marker = DONE if doc["stats"]["complete"] else PARTIAL
        (self.dir / marker).write_text(version, encoding="utf-8")

    def cached_version(self) -> str | None:
        """The DCS version of the cached document (complete or partial)."""
        if not (self.dir / self.file).is_file():
            return None
        return self.marker(DONE) or self.marker(PARTIAL)

    def load(self, version: str) -> dict[str, Any] | None:
        """The cached document when it is ``version``'s, else None."""
        if version not in (self.marker(DONE), self.marker(PARTIAL)):
            return None
        path = self.dir / self.file
        return load_json(path) if path.is_file() else None

    def version_files(self, version: str, data_root: Path) -> dict[str, bytes]:
        """``{"api/<file>": bytes}`` for DCS ``version``: the cached document
        when it is ``version``'s, else ``latest``'s own or carried forward
        (``version_probe``), else nothing."""
        rel = f"{API_DIR}/{self.file}"
        cached = version in (self.marker(DONE), self.marker(PARTIAL))
        if cached and (self.dir / self.file).is_file():
            return {rel: (self.dir / self.file).read_bytes()}
        doc = version_probe(data_root, version, self.file)
        return {rel: json_text(doc).encode("utf-8")} if doc else {}


def install_probe(
    doc: dict[str, Any], file: str, data_root: Path = REFERENCE_DATA_DIR
) -> Path | None:
    """Put probe document ``doc`` in ``<data_root>/latest`` as ``api/<file>``
    when ``latest`` is its DCS version; the ``latest`` dir, else None."""
    latest = version_data(data_root, doc["dcsVersion"])
    if latest is None:
        return None
    write_text_if_changed(latest / API_DIR / file, json_text(doc))
    return latest


def read_progress(path: Path) -> str:
    """A probe's progress file; empty when it is absent."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def progress_lines(text: str) -> tuple[str | None, list[tuple[str, str]]]:
    """(the plan id of the first line ``P<tab>id``, ``[(tag, rest)]`` of the
    other lines) of a probe's progress file."""
    lines = text.splitlines()
    plan_id = lines[0][2:] if lines and lines[0].startswith("P\t") else None
    return plan_id, [
        (tag, rest) for tag, _, rest in (x.partition("\t") for x in lines[1:])
    ]


def load_plan_lua(text: str, name: str, what: str, items: str) -> dict[str, Any]:
    """The table a probe plan hook file (``return { ... }``) returns; it must
    have a list ``items``."""
    from .lua_reader import lua_to_py, sandbox_exec

    ok, env = sandbox_exec(f"__plan = (function()\n{text}\nend)()", name)
    if not ok:
        fail(f"cannot read the {what} plan: {env}")
    p = lua_to_py(env["__plan"])
    if not isinstance(p, dict) or not isinstance(p.get(items), list):
        fail(f"the {what} plan has no {items}")
    return p


def load_series(
    data_dir: Path, name: str, required: bool = False
) -> dict[str, dict[str, Any]]:
    """``{file stem: record}`` of a data dir's series ``name``; empty when
    it is absent, unless ``required``."""
    d = data_dir / name
    if not d.is_dir():
        if required:
            fail(f"no {name} series in {data_dir} (run the extraction first)")
        return {}
    paths = sorted(d.glob("*.json"))
    return dict(zip((p.stem for p in paths), pmap(load_json, paths), strict=True))


def generated_drift(out: Path, files: dict[str, str], suffix: str) -> list[str]:
    """The ``*<suffix>`` files under ``out`` that differ from ``files``
    (missing, changed, or not in ``files``), sorted."""
    on_disk = {p.name for p in out.glob(f"*{suffix}")}
    return [
        n
        for n in sorted(files.keys() | on_disk)
        if n not in on_disk
        or n not in files
        or (out / n).read_bytes() != files[n].encode("utf-8")
    ]


def write_generated(out: Path, files: dict[str, str], suffix: str) -> None:
    """Make the ``*<suffix>`` files under ``out`` exactly ``files``."""
    for p in sorted(out.glob(f"*{suffix}")):
        if p.name not in files:
            p.unlink()
            print(f"Removed {p}")
    for name, text in sorted(files.items()):
        if write_text_if_changed(out / name, text):
            print(f"Regenerated {out / name}")


def assign_defined(target: dict[str, Any], fields: dict[str, Any]) -> None:
    """Copy only the non-``None`` entries of ``fields`` into ``target``."""
    for key, value in fields.items():
        if value is not None:
            target[key] = value


def walk_lua(directory: Path) -> list[Path]:
    """Every ``*.lua`` under ``directory`` (recursive), sorted."""
    out: list[Path] = []
    for root, _dirs, files in os.walk(directory):
        out.extend(Path(root, f) for f in files if f.endswith(".lua"))
    return sorted(out, key=str)


def list_lua(directory: Path) -> list[Path]:
    """Direct ``*.lua`` children of ``directory``, sorted by name."""
    try:
        with os.scandir(directory) as it:
            names = [e.name for e in it if e.name.endswith(".lua") and e.is_file()]
    except FileNotFoundError:
        return []
    return [directory / n for n in sorted(names)]
