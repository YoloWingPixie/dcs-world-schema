"""The shared conformance vectors of the reference helpers
(tools/package/tests/vectors/helpers.json) in Lua 5.1, through ``helpers.lua``.
Lua cannot tell ``[]`` from ``{}``: both compare as empty."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.package.lua_data import lua_value
from tools.package.vectors import VECTORS

LUA_DIR = Path(__file__).resolve().parents[1]
LUA = shutil.which("lua5.1") or shutil.which("luajit")

pytestmark = pytest.mark.skipif(LUA is None, reason="lua5.1 or luajit not installed")


def _close(got: Any, want: Any, tol: dict[str, float], path: str) -> None:
    if want in ([], {}) or got in ([], {}):
        assert got in ([], {}) and want in ([], {}), (path, got, want)
    elif isinstance(want, bool) or want is None or isinstance(want, str):
        assert got == want, (path, got, want)
    elif isinstance(want, int | float):
        assert isinstance(got, int | float) and not isinstance(got, bool), path
        assert abs(got - want) <= tol["abs"] + tol["rel"] * abs(want), (path, got, want)
    elif isinstance(want, list):
        assert isinstance(got, list) and len(got) == len(want), (path, got)
        for i, (g, w) in enumerate(zip(got, want, strict=True)):
            _close(g, w, tol, f"{path}[{i}]")
    else:
        assert isinstance(got, dict) and sorted(got) == sorted(want), (path, got)
        for k, w in want.items():
            _close(got[k], w, tol, f"{path}.{k}")


def _lua_case(case: dict[str, Any]) -> str:
    args = ",".join(
        f"[{i}]={lua_value(a)}" for i, a in enumerate(case["args"], 1) if a is not None
    )
    return f"{{fn={lua_value(case['fn'])},n={len(case['args'])},args={{{args}}}}}"


def test_vectors(tmp_path: Path) -> None:
    assert LUA is not None
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    cases = vectors["cases"]
    script = tmp_path / "cases.lua"
    script.write_text(
        "return {\n" + ",\n".join(_lua_case(c) for c in cases) + "\n}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [LUA, "tests/helpers.lua", str(LUA_DIR), str(script)],
        cwd=LUA_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    got = json.loads(result.stdout)
    assert len(got) == len(cases)
    for case, out in zip(cases, got, strict=True):
        label = f"{case['fn']}{json.dumps(case['args'])[:100]}"
        if case.get("throws"):
            assert out.get("throws"), (label, out)
        else:
            assert not out.get("throws"), (label, out.get("error"))
            _close(out["value"], case["expect"], vectors["tolerance"], label)
