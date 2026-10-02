"""JSON values as Lua 5.1 table constructors.

Keys are sorted and every string is escaped for a double-quoted Lua literal
(control characters as ``\\ddd``; UTF-8 bytes as they are), so the output is
deterministic and loads in plain Lua 5.1 and in DCS. Lua cannot tell ``[]`` from
``{}`` and has no ``null``: both empty containers become ``{}`` and ``null``
becomes an absent key (the data has none).
"""

from __future__ import annotations

import math
import re
from typing import Any

KEYWORDS = frozenset(
    "and break do else elseif end false for function if in local nil not or "
    "repeat return then true until while goto".split()
)
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_SPECIAL = re.compile(r'[\\"\x00-\x1f\x7f]')


def lua_string(s: str) -> str:
    def esc(m: re.Match[str]) -> str:
        c = m.group()
        return _ESCAPES.get(c) or f"\\{ord(c):03d}"

    return '"' + _SPECIAL.sub(esc, s) + '"'


def is_lua_name(name: str) -> bool:
    """Whether ``name`` can be written bare: an ASCII identifier, not a keyword."""
    return name.isascii() and name.isidentifier() and name not in KEYWORDS


def lua_key(k: str) -> str:
    return k if is_lua_name(k) else f"[{lua_string(k)}]"


def lua_value(v: Any) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError(f"non-finite number {v!r}")
        return str(int(v)) if v.is_integer() and abs(v) < 2**53 else repr(v)
    if isinstance(v, str):
        return lua_string(v)
    if isinstance(v, list):
        return "{" + ",".join(lua_value(x) for x in v if x is not None) + "}"
    if isinstance(v, dict):
        return (
            "{"
            + ",".join(
                f"{lua_key(k)}={lua_value(x)}"
                for k, x in sorted(v.items())
                if x is not None
            )
            + "}"
        )
    if v is None:
        raise ValueError("null outside a table")
    raise TypeError(f"not a JSON value: {v!r}")


def lua_inline(value: Any) -> str:
    """``value`` as one Lua expression: numbers as Python writes them, lists
    as ``{a, b}``, dicts as ``{[key] = value}`` with sorted keys (a hook
    file's plan entries)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, list):
        return "{" + ", ".join(lua_inline(v) for v in value) + "}"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(
                f"[{lua_inline(k)}] = {lua_inline(v)}" for k, v in sorted(value.items())
            )
            + "}"
        )
    raise TypeError(f"no Lua literal for {type(value).__name__}")


def lua_module(payload: dict[str, Any], header: str) -> str:
    """``return <payload>`` for a small table."""
    return f"-- {header}\nreturn {lua_value(payload)}\n"


def lua_bundle(bundle: dict[str, Any], header: str) -> str:
    """``return {["key"] = record, ...}``, one record per line, keys sorted."""
    lines = [f"-- {header}", "return {"]
    for k in sorted(bundle):
        lines.append(f"[{lua_string(k)}]={lua_value(bundle[k])},")
    lines.append("}")
    return "\n".join(lines) + "\n"
