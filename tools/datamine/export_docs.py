"""ED's documentation of the export ``Lo*`` functions, from the comments of the
install's ``Scripts/Export.lua`` (read only; nothing there is executed).

The file documents the functions in prose, not in a fixed format, so only what
its lines state literally is taken:

* An entry is a line that, after an optional ``--`` and whitespace, starts with
  a ``Lo<Name>`` identifier (or ``{...} = Lo<Name>``, whose left side becomes
  ``assigns``), optionally followed by ``(args)`` naming parameters (words, not
  literal values), and then by more text: a ``--`` comment, prose, ``= ...``.
  A line holding just ``Lo<Name>(params)`` counts only as a ``--`` comment line
  (inside the big comment block such lines are example code); one holding just
  ``{...} = Lo<Name>(params)`` always counts. Lines of example
  code (``local x = Lo...``, calls with literal arguments) never match.
* ``argsCount`` and ``results`` are read from ``(args - N, results - ...)``
  (or ``args N ...``) in that text; a range (``args - 0- 1``) gives no
  ``argsCount``. ``params`` are the names in the parentheses.
* ``detail`` holds the lines that follow an entry verbatim (the returned table
  layouts and value lists), up to the next entry, a section header, the end
  of the comment block or, outside the block, the end of the comment run.
* ``fields`` are the names at the top level of the first ``{ ... }`` in
  ``detail`` (``name =``, ``name,`` or a bare ``name``) - names only, as
  written. A block whose braces do not close on a line of its own (a typo)
  gives none.
* ``section`` is the header the entry is under (``Output:``, ``Input:``,
  ``-- Weapon Control System``, ...), when there is one.

Entries of the same function (the file lists a few twice) are kept in file
order under that name.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SOURCE = "Scripts/Export.lua comments"
REL_PATH = "Scripts/Export.lua"
FORMAT = "dcs-export-docs/1"

_ENTRY = re.compile(
    r"^(?:(?P<assigns>\{[^}]*\})\s*=\s*)?"
    r"(?P<name>Lo[A-Z]\w*)\b\s*"
    r"(?:\((?P<params>[^()]*)\))?"
    r"(?P<rest>.*)$"
)
_PARAM = re.compile(r"^[A-Za-z_][\w/]*$")
_ARGS = re.compile(r"\bargs\s*(?:-\s*)?(\d+)(?=\s*(?:[,):(]|$))")
_RESULTS = re.compile(r"\bresults?\s*[-=]\s*(.+)$")
_FIELD = re.compile(r"^([A-Za-z_]\w*)\s*(?:=|,|--|\(|$)")
_SECTION = re.compile(r"^(?:[A-Z][^=()]*:|--\s+[A-Z][\w ]*)$")
_BLOCK_OPEN = re.compile(r"^--\[(=*)\[")
_INNER_OPEN = re.compile(r"--\[(=+)\[")


def _params(text: str | None) -> list[str] | None:
    """The parameter names of ``(text)``; None when it holds anything else."""
    if text is None:
        return []
    parts = [p.strip() for p in text.split(",")] if text.strip() else []
    return parts if all(_PARAM.match(p) for p in parts) else None


def _args_group(rest: str) -> str:
    """The inside of ``(args ...)`` in ``rest`` (to the end when unclosed), or
    ``rest`` when it has none."""
    start = rest.find("(args")
    if start < 0:
        return rest
    depth = 0
    for i in range(start, len(rest)):
        depth += {"(": 1, ")": -1}.get(rest[i], 0)
        if depth == 0:
            return rest[start + 1 : i]
    return rest[start + 1 :]


def _entry(
    text: str, commented: bool, in_block: bool
) -> tuple[dict[str, Any], str] | None:
    m = _ENTRY.match(text)
    if not m:
        return None
    params = _params(m.group("params"))
    if params is None:
        return None
    rest = m.group("rest").strip().removeprefix(";").strip()
    if (
        not rest
        and not m.group("assigns")
        and (in_block or not commented or m.group("params") is None)
    ):
        return None
    entry: dict[str, Any] = {"name": m.group("name"), "params": params}
    if m.group("params") is None:
        entry.pop("params")
    if m.group("assigns"):
        entry["assigns"] = m.group("assigns")
    if rest:
        entry["text"] = rest
        group = _args_group(rest)
        if a := _ARGS.search(group):
            entry["argsCount"] = int(a.group(1))
        if r := _RESULTS.search(group):
            entry["results"] = r.group(1).strip()
    return entry, m.group("name")


def _fields(detail: list[str]) -> list[str]:
    """Top-level names of the first ``{...}`` in ``detail``."""
    names: list[str] = []
    depth = 0
    started = False
    long_comment: str | None = None
    for line in detail:
        text = line.strip()
        if long_comment is not None:
            if f"]{long_comment}]" in text:
                long_comment = None
            continue
        if m := _INNER_OPEN.search(text):
            long_comment = m.group(1)
            continue
        code = text.split("--", 1)[0]
        if (
            depth == 1
            and started
            and (f := _FIELD.match(code.lstrip("{").strip()))
            and f.group(1) not in names
        ):
            names.append(f.group(1))
        for ch in code:
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
        if started and depth <= 0:
            # A clean close is a line of just ``}``; anything else is a typo in
            # the layout (``y = (x = ..}``), and its names are not trusted.
            return names if code.strip().rstrip(",") == "}" else []
        if not started and depth == 0 and "{" in code:
            started = True
    return names


def parse(text: str) -> dict[str, list[dict[str, Any]]]:
    """``{function name: [entry, ...]}`` of Export.lua's text (module docstring)."""
    lines = text.splitlines()
    out: dict[str, list[dict[str, Any]]] = {}
    in_block = False
    section: str | None = None
    current: dict[str, Any] | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            detail = current.pop("_detail")
            while detail and not detail[-1].strip():
                detail.pop()
            if detail:
                current["detail"] = detail
                if fields := _fields(detail):
                    current["fields"] = fields
            out.setdefault(current["name"], []).append(current)
        current = None

    def next_is_entry(i: int, block: bool) -> bool:
        for later in lines[i + 1 :]:
            if later.strip():
                stripped = later.strip()
                commented = stripped.startswith("--")
                body = stripped[2:].strip() if commented else stripped
                return _entry(body, commented, block) is not None
        return False

    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if not in_block and (opened := _BLOCK_OPEN.match(stripped)):
            close()
            in_block = True
            section = None
            stripped = stripped[opened.end() :].strip()
            if not stripped:
                continue
        if in_block and stripped.startswith("--]]"):
            close()
            in_block = False
            section = None
            continue
        commented = stripped.startswith("--")
        body = stripped[2:].strip() if commented else stripped
        found = _entry(body, commented, in_block) if (in_block or commented) else None
        if found:
            close()
            entry, _ = found
            if section:
                entry["section"] = section
            entry["line"] = i + 1
            entry["_detail"] = []
            current = entry
            continue
        at_col0 = raw[:1] not in (" ", "\t")
        if (
            in_block
            and at_col0
            and _SECTION.match(stripped)
            and next_is_entry(i, in_block)
        ):
            close()
            section = stripped
            continue
        if current is None:
            continue
        if in_block:
            current["_detail"].append(raw.rstrip())
        elif commented and stripped:
            current["_detail"].append(body)
        else:
            close()
    close()
    return {name: out[name] for name in sorted(out)}


def document(install_dir: Path) -> dict[str, Any] | None:
    """The docs file's payload for ``install_dir``; None without Export.lua."""
    path = install_dir / REL_PATH
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    return {"format": FORMAT, "source": SOURCE, "functions": parse(text)}
