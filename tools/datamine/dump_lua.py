"""The ``_G`` dump files the reference data points into, for the site's
"View Lua" drawer.

Every dump path a record emits (``sourcePaths`` and the dump-path part of
each block's ``sourcePath``, ``dump_paths``) names one file of the dump
(``_G/a/b`` is ``<g_dir>/a/b.lua``). The dump is not committed: it is
published as a release asset, one per DCS version (``RELEASE_TAG``,
``ASSET``: a ``tar.gz`` of the whole ``_G`` dir, made by ``pack``). The site
build copies the referenced files, byte for byte, out of the cached dump or
that asset (``collect``) and publishes them (site/scripts/copy-lua-assets.ts).

    uv run python -m tools.datamine.dump_lua pack [G_DIR] [--out FILE]
    uv run python -m tools.datamine.dump_lua collect (--g-dir DIR | --archive FILE)
        --out DIR [--data-root DIR]
    uv run python -m tools.datamine.dump_lua version [--data-root DIR]

``collect`` checks the dump is the DCS version of ``<data-root>/latest`` and
makes ``--out`` hold exactly the referenced files (others are deleted).
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import tarfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .common import (
    CACHED_G_DIR,
    DIST_DIR,
    LATEST,
    REFERENCE_DATA_DIR,
    VERSION_MARKER,
    fail,
    latest_version,
    pmap,
    read_version,
    series_records,
    sync_tree,
    tree_files,
)
from .dump_paths import emitted_paths

G_PREFIX = "_G/"
ROOT = "_G"  # the archive's top-level dir


def release_tag(version: str) -> str:
    """The GitHub release holding DCS ``version``'s dump."""
    return f"dcs-dump-{version}"


def asset_name(version: str) -> str:
    """The dump asset of DCS ``version``."""
    return f"dcs-g-dump-{version}.tar.gz"


def dump_file(path: str) -> str:
    """The dump-relative file (``a/b.lua``) of dump path ``path``
    (``_G/a/b``, a ``#pointer`` ignored)."""
    path = path.partition("#")[0]
    if not path.startswith(G_PREFIX) or len(path) == len(G_PREFIX):
        raise ValueError(f"not a _G dump path: {path!r}")
    rel = path[len(G_PREFIX) :]
    if any(seg in ("", ".", "..") for seg in rel.split("/")):
        raise ValueError(f"bad dump path: {path!r}")
    return f"{rel}.lua"


def referenced(records: Iterable[Any]) -> list[str]:
    """The sorted dump-relative files of every dump path in ``records``."""
    return sorted({dump_file(p) for rec in records for _, p in emitted_paths(rec)})


def latest_records(data_root: Path) -> tuple[str, list[Any]]:
    """``(DCS version, every record of <data_root>/latest with a dump path)``."""
    version = latest_version(data_root)
    if version is None:
        fail(f"no {data_root / LATEST}")
    paths = series_records(tree_files(data_root / LATEST))
    files = [p for records in paths.values() for p in records.values()]
    texts = pmap(Path.read_bytes, files)
    return version, [json.loads(b) for b in texts if b'"sourcePath' in b]


def _member_version(tar: tarfile.TarFile) -> str | None:
    try:
        member = tar.extractfile(f"{ROOT}/{VERSION_MARKER}")
    except KeyError:
        return None
    if member is None:
        return None
    return member.read().decode("utf-8", errors="replace").strip() or None


def collect(
    data_root: Path, out: Path, g_dir: Path | None = None, archive: Path | None = None
) -> dict[str, bytes]:
    """Make ``out`` hold exactly the dump files (``a/b.lua``) the records of
    ``<data_root>/latest`` reference, read from the dump dir ``g_dir`` or the
    dump ``archive`` (``pack``); fails when the dump is another DCS version or
    lacks one. The files."""
    version, records = latest_records(data_root)
    wanted = referenced(records)
    if g_dir is not None:
        if (dumped := read_version(g_dir)) != version:
            fail(f"{g_dir} is DCS {dumped}, {data_root / LATEST} is DCS {version}")
        missing = [f for f in wanted if not (g_dir / f).is_file()]
        if missing:
            fail(
                f"{len(missing)} referenced dump file(s) not in {g_dir}: {missing[:5]}"
            )
        files = dict(
            zip(wanted, pmap(lambda f: (g_dir / f).read_bytes(), wanted), strict=True)
        )
    elif archive is not None:
        with tarfile.open(archive, "r:gz") as tar:
            if (dumped := _member_version(tar)) != version:
                fail(
                    f"{archive} is DCS {dumped}, {data_root / LATEST} is DCS {version}"
                )
            files = {}
            want = set(wanted)
            for member in tar:
                rel = member.name.removeprefix(f"{ROOT}/")
                if member.isfile() and rel in want:
                    data = tar.extractfile(member)
                    assert data is not None
                    files[rel] = data.read()
        missing = sorted(set(wanted) - set(files))
        if missing:
            fail(
                f"{len(missing)} referenced dump file(s) not in {archive}: {missing[:5]}"
            )
    else:
        raise ValueError("collect needs g_dir or archive")
    sync_tree(out, {out / rel: b for rel, b in files.items()})
    return files


def pack(g_dir: Path, out: Path) -> str:
    """Write the dump ``g_dir`` to ``out`` as the release asset: a
    ``tar.gz`` of ``_G/`` with sorted entries and no times or owners, so the
    same dump packs to the same bytes. Its DCS version."""
    version = read_version(g_dir)
    if version is None:
        fail(f"no {VERSION_MARKER} in {g_dir}")
    files = sorted(
        p.relative_to(g_dir).as_posix() for p in g_dir.rglob("*") if p.is_file()
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for rel in files:
            data = (g_dir / rel).read_bytes()
            info = tarfile.TarInfo(f"{ROOT}/{rel}")
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    with (
        out.open("wb") as fh,
        gzip.GzipFile(
            filename="", mode="wb", fileobj=fh, mtime=0, compresslevel=9
        ) as gz,
    ):
        gz.write(buf.getvalue())
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_pack = sub.add_parser("pack", help="Pack a dump as the release asset.")
    p_pack.add_argument("g_dir", type=Path, nargs="?", default=CACHED_G_DIR)
    p_pack.add_argument("--out", type=Path, help="Default: dist/<asset name>.")
    p_collect = sub.add_parser("collect", help="Copy the referenced dump files.")
    src = p_collect.add_mutually_exclusive_group(required=True)
    src.add_argument("--g-dir", type=Path)
    src.add_argument("--archive", type=Path)
    p_collect.add_argument("--out", type=Path, required=True)
    p_collect.add_argument("--data-root", type=Path, default=REFERENCE_DATA_DIR)
    p_version = sub.add_parser(
        "version", help="Print latest's DCS version, release tag and asset name."
    )
    p_version.add_argument("--data-root", type=Path, default=REFERENCE_DATA_DIR)
    args = parser.parse_args()

    if args.cmd == "pack":
        version = read_version(args.g_dir) or fail(
            f"no {VERSION_MARKER} in {args.g_dir}"
        )
        out = args.out or DIST_DIR / asset_name(version)
        pack(args.g_dir, out)
        print(f"DCS {version}: {out} ({out.stat().st_size / 1e6:.1f} MB)")
        print(f"Release: gh release create {release_tag(version)} {out} --latest=false")
    elif args.cmd == "collect":
        files = collect(args.data_root, args.out, args.g_dir, args.archive)
        size = sum(map(len, files.values()))
        print(f"{len(files)} dump files ({size / 1e6:.1f} MB) -> {args.out}")
    else:
        version = latest_version(args.data_root) or fail(
            f"no {args.data_root / LATEST}"
        )
        print(
            json.dumps(
                {
                    "version": version,
                    "tag": release_tag(version),
                    "asset": asset_name(version),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
