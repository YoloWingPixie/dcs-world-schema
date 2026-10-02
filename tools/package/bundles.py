"""Bundle ``dcs-world-reference/latest/`` into one JSON file per series.

Each bundle is an object of ``key -> record``, keys sorted, written compact with
sorted record keys, so the output depends only on the data. The key is the
series' id field (``common.SERIES``). A duplicate key is an error. ``manifest.json`` is
copied beside the bundles.

    uv run python -m tools.package.bundles [--data DIR] [--output DIR]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.datamine.common import (
    DIST_DIR,
    LATEST,
    MANIFEST,
    REFERENCE_DATA_DIR,
    SERIES,
    Series,
    fail,
    json_text,
    read_tree,
    series_records,
    write_text_if_changed,
)

BUNDLE_DIR = DIST_DIR / "reference"


def build_bundle(series: Series, records: dict[str, Any]) -> dict[str, Any]:
    """``{key: record}`` of a series' ``{file stem: record}``, keys sorted."""
    key_field = series.id_field
    out: dict[str, Any] = {}
    for stem, record in records.items():
        key = record.get(key_field)
        if not isinstance(key, str | int) or isinstance(key, bool):
            fail(f"{series.name}/{stem}.json: no {key_field!r} to key the bundle by")
        key = str(key)
        if key in out:
            fail(f"{series.name}/{stem}.json: duplicate {key_field} {key!r}")
        out[key] = record
    return dict(sorted(out.items()))


@dataclass
class Bundles:
    series: dict[str, dict[str, Any]]  # series -> bundle
    manifest: dict[str, Any]
    files: dict[str, str]  # file name -> text, as written


def build(data_dir: Path, output: Path) -> Bundles:
    """Write ``<output>/<series>.json`` and ``manifest.json``; unchanged files
    are not rewritten."""
    tree = read_tree(data_dir)
    if MANIFEST not in tree:
        fail(f"no {MANIFEST} in {data_dir}")
    by_series = series_records(tree)
    out = Bundles({}, json.loads(tree[MANIFEST]), {})
    for series in SERIES.values():
        if series.name not in by_series:
            fail(f"no {series.name}/ under {data_dir}")
        records = {s: json.loads(b) for s, b in by_series[series.name].items()}
        out.series[series.name] = bundle = build_bundle(series, records)
        out.files[f"{series.name}.json"] = json_text(bundle, compact=True)
    out.files[MANIFEST] = json_text(out.manifest, compact=True)
    for name, text in out.files.items():
        write_text_if_changed(output / name, text)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=REFERENCE_DATA_DIR / LATEST)
    parser.add_argument("--output", type=Path, default=BUNDLE_DIR)
    args = parser.parse_args()
    series = build(args.data, args.output).series
    total = sum(len(b) for b in series.values())
    print(f"Wrote {len(series)} bundles ({total} records) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
