"""Shared test helpers (``tools/datamine/tests`` is on the pytest pythonpath)."""

import functools
import json
from pathlib import Path
from typing import Any

from tools.datamine.common import LATEST, MANIFEST, REPO_ROOT
from tools.datamine.rwr import WsTypeIds
from tools.export_jsonschema import export
from tools.merge import merge_tree

NO_IDS = WsTypeIds(units={}, stores={}, projectiles={}, ammunition={})


@functools.cache
def entity_schema() -> dict[str, Any]:
    """The entity JSON Schema of the repo's spec."""
    merged, _ = merge_tree(str(REPO_ROOT / "dcs-world-schema"))
    return export(merged["types"])


def write(path: Path, text: str) -> Path:
    """Write ``text`` to ``path``, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def hold(data_root: Path, version: str) -> None:
    """Make ``<data_root>/latest`` DCS ``version``'s (its manifest)."""
    write(data_root / LATEST / MANIFEST, json.dumps({"dcsVersion": version}))


def unresolved_paths(record: Any, g_dir: Path, dump_format: int = 3) -> list[str]:
    """``dump_paths.check`` of one entity ``record`` against the dump in
    ``g_dir``: every ``sourcePaths`` entry or ``sourcePath`` that does not
    resolve."""
    from tools.datamine.dump_paths import DumpPaths, check
    from tools.datamine.lua_reader import LuaReader

    reader = LuaReader(g_dir, link_refs=False, dump_format=dump_format)
    return check(DumpPaths(g_dir, reader), {"record": {"x": record}})
