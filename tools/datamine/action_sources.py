"""Parameter and capability facts read from DCS's Lua source text: the
Mission Editor's, for what the loaded tables (``me-action-db.lua``) cannot
show, and the task tables of DCS's own scripts.

* ``declared``: the keys an ``actionsData`` entry of ``me_action_db.lua``
  writes as ``key = nil`` (Lua drops them from the loaded default task).
* ``returned``: the top-level keys of every ``return { ... }`` table
  constructor in a function's lines, and in the lines of the module functions
  it calls (one level): what ``makeParams`` adds to a new action's params.
* ``panel_params``: per ``ActionId`` name, every ``actionParams.<key>`` in its
  ``paramPanelConstructors`` entry of ``me_action_edit_panel.lua``, in the
  file's local functions that entry calls and in the parameter panels
  (``me_action_param_panels.lua``) either uses, transitively.
* ``capability``: the attributes (``findAttribute(..., "<attribute>")``) and
  messages (``_("...")``) in a capability function's lines and the module
  functions it calls (one level).
* ``script_actions``: the task and command tables DCS's own scripts
  (``Scripts/``, ``CoreMods/``, ``Mods/``) pass to ``Controller.setCommand``/``setTask``/``pushTask``:
  their ``id`` and ``params`` keys.

Function line ranges come from ``luac5.1 -p -l`` (nested functions included)
or from the loader (``debug.getinfo``). These are text scans of DCS's source:
a key read another way (``actionParams[k]``, a renamed local) is not seen.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from .common import fail

_ACTIONS_DATA = re.compile(r"^actionsData\s*=\s*\{", re.M)
_BLOCK = re.compile(r"^\s*\[ActionId\.(\w+)\]\s*=")
_NIL_KEY = re.compile(r"^\s*(\w+)\s*=\s*nil\s*,?\s*(?:--.*)?$")
_PARAM_REF = re.compile(r"\bactionParams\.(\w+)")
_PANEL_REF = re.compile(r"\bactionParamPanels\.(\w+)")
_PANEL_CREATE = re.compile(r"\b([A-Z]\w*)\s*:\s*create\s*\(")
_CONSTRUCTOR = re.compile(r"^\s*\[actionDB\.ActionId\.(\w+)\]\s*=\s*function\b")
_LOCAL_FUNCTION = re.compile(r"^\s*(?:local\s+)?function\s+([A-Za-z_]\w*)\s*\(")
_PANEL_DEF = re.compile(r"^\t([A-Z]\w*)\s*=\s*\{")
_ATTRIBUTE = re.compile(r"findAttribute\s*\([^,()]+,\s*(['\"])(.+?)\1")
_MESSAGE = re.compile(r"\b_\(\s*(['\"])(.+?)\1\s*\)")
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_LUAC_FUNCTION = re.compile(r"^function <[^>]*:(\d+),(\d+)>", re.M)
_RETURN_TABLE = re.compile(r"\breturn\s*\{")
_KEY = re.compile(r"([A-Za-z_]\w*)\s*=(?!=)")


def luac51() -> str:
    luac = shutil.which("luac5.1")
    if luac is None:
        fail(
            "luac5.1 not found: the actions extraction reads Mission Editor function ranges with it"
        )
    return luac


def function_ranges(path: Path) -> dict[int, int]:
    """``{first line: last line}`` of every function in a Lua file (``luac5.1``)."""
    proc = subprocess.run(
        [luac51(), "-p", "-l", str(path)], capture_output=True, text=True, check=False
    )
    if proc.returncode:
        fail(f"luac5.1 -p -l {path}: {proc.stderr.strip()}")
    out: dict[int, int] = {}
    for m in _LUAC_FUNCTION.finditer(proc.stdout):
        start, end = int(m.group(1)), int(m.group(2))
        out[start] = max(end, out.get(start, 0))
    return out


def _span(lines: list[str], first: int, last: int) -> str:
    """Lines ``first``..``last`` (1-based, inclusive)."""
    return "\n".join(lines[first - 1 : last])


def _strip_comments(text: str, keep_lines: bool = False) -> str:
    """``text`` without comments; ``keep_lines``: a block comment leaves its
    newlines, so line numbers stay."""

    def block(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n") if keep_lines else ""

    text = re.sub(r"--\[(=*)\[.*?\]\1\]", block, text, flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


def declared(text: str) -> dict[str, list[str]]:
    """``{ActionId name: [keys written as key = nil]}`` of ``actionsData``."""
    m = _ACTIONS_DATA.search(text)
    if m is None:
        fail("me_action_db.lua has no `actionsData = {`")
    lines = text[m.start() :].split("\n")
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[1:]:
        if line.startswith("}"):
            break
        block = _BLOCK.match(line)
        if block:
            current = block.group(1)
            continue
        key = _NIL_KEY.match(line)
        if key and current:
            names = out.setdefault(current, [])
            if key.group(1) not in names:
                names.append(key.group(1))
    return {k: sorted(v) for k, v in out.items()}


def _constructor_fields(text: str, start: int) -> dict[str, str]:
    """``{key: value text}`` of the ``key = value`` fields of the table
    constructor whose ``{`` is at ``start``."""
    depth, i, items, item_start = 0, start, [], start + 1
    while i < len(text):
        c = text[i]
        if c in "\"'":
            j = i + 1
            while j < len(text) and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if c in "{([":
            depth += 1
        elif c in "})]":
            depth -= 1
            if depth == 0:
                items.append(text[item_start:i])
                break
        elif depth == 1 and c in ",;":
            items.append(text[item_start:i])
            item_start = i + 1
        i += 1
    fields = {}
    for item in items:
        if m := _KEY.match(item.strip()):
            fields[m.group(1)] = item.strip()[m.end() :].strip()
    return fields


def _constructor_keys(text: str, start: int) -> set[str]:
    """Top-level keys of the table constructor whose ``{`` is at ``start``."""
    return set(_constructor_fields(text, start))


_CONTROLLER_CALL = re.compile(r":\s*(setCommand|setTask|pushTask)\s*\(\s*")
_FUNCTION_NAME = re.compile(r"\bfunction\s+([A-Za-z_][\w.:]*)\s*\(")
_NUMBER = re.compile(r"^-?(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+)$")
_STRING = re.compile(r"^(['\"])(\w+)\1$")


def _literal_type(value: str) -> str | None:
    """The Lua type of a literal value text; None for an expression."""
    if value in ("true", "false"):
        return "boolean"
    if _NUMBER.match(value):
        return "number"
    if value[:1] in "\"'" or value.startswith("[["):
        return "string"
    if value.startswith("{"):
        return "table"
    return None


@dataclass(frozen=True)
class ScriptAction:
    """A task or command table a DCS script passes to a controller."""

    dcs_id: str
    call: str  # setCommand, setTask or pushTask
    function: str | None  # the named function making the call
    params: dict[str, list[str]]  # name -> Lua types of its literal value


def script_actions(text: str, ranges: dict[int, int]) -> list[ScriptAction]:
    """Every ``controller:setCommand/setTask/pushTask(t)`` of a Lua file
    whose ``t`` is a table constructor with a string ``id``, inline or the
    last ``t = { ... }`` before the call; ``ranges``: the file's function
    line ranges (``function_ranges``), naming the innermost named function
    around the call. Calls of other tables are not seen."""
    text = _strip_comments(text, keep_lines=True)
    lines = text.split("\n")
    out = []
    for m in _CONTROLLER_CALL.finditer(text):
        start = m.end()
        if not text.startswith("{", start):
            var = re.match(r"([A-Za-z_]\w*)\s*\)", text[start:])
            if var is None:
                continue
            assigned = list(
                re.finditer(rf"\b{var.group(1)}\s*=\s*(?=\{{)", text[: m.start()])
            )
            if not assigned:
                continue
            start = assigned[-1].end()
        fields = _constructor_fields(text, start)
        dcs_id = _STRING.match(fields.get("id", ""))
        if dcs_id is None:
            continue
        params: dict[str, list[str]] = {}
        raw = fields.get("params", "")
        if raw.startswith("{"):
            for k, v in _constructor_fields(raw, 0).items():
                t = _literal_type(v)
                params[k] = [t] if t else []
        line = text.count("\n", 0, m.start()) + 1
        named = [
            (first, n.group(1))
            for first, last in ranges.items()
            if first <= line <= last and (n := _FUNCTION_NAME.search(lines[first - 1]))
        ]
        out.append(
            ScriptAction(
                dcs_id.group(2), m.group(1), max(named)[1] if named else None, params
            )
        )
    return out


def _returned_here(body: str) -> set[str]:
    keys: set[str] = set()
    for m in _RETURN_TABLE.finditer(body):
        keys |= _constructor_keys(body, m.end() - 1)
    return keys


@dataclass
class ModuleSource:
    """A Mission Editor module file with its function names' line ranges
    (the loader's ``functions``)."""

    text: str
    functions: dict[str, tuple[int, int]] = field(default_factory=dict)

    @cached_property
    def lines(self) -> list[str]:
        return self.text.split("\n")

    def body(self, first: int, last: int) -> str:
        return _strip_comments(_span(self.lines, first, last))

    def _with_callees(self, first: int, last: int) -> list[str]:
        body = self.body(first, last)
        bodies = [body]
        for name in sorted({m.group(1) for m in _CALL.finditer(body)}):
            rng = self.functions.get(name)
            if rng and not (first <= rng[0] <= last):
                bodies.append(self.body(*rng))
        return bodies

    def returned(self, first: int, last: int) -> list[str]:
        keys: set[str] = set()
        for body in self._with_callees(first, last):
            keys |= _returned_here(body)
        return sorted(keys)

    def capability(self, first: int, last: int) -> tuple[list[str], list[str]]:
        """(attributes, messages) of a capability function."""
        attributes: set[str] = set()
        messages: list[str] = []
        for body in self._with_callees(first, last):
            attributes |= {m.group(2) for m in _ATTRIBUTE.finditer(body)}
            for m in _MESSAGE.finditer(body):
                if m.group(2) not in messages:
                    messages.append(m.group(2))
        return sorted(attributes), messages


def panel_params(
    edit_text: str,
    edit_ranges: dict[int, int],
    panels_text: str,
    panels_ranges: dict[int, int],
) -> dict[str, list[str]]:
    """``{ActionId name: [actionParams keys]}`` of the parameter panels."""
    edit = _strip_comments(edit_text, keep_lines=True).split("\n")
    panels = _strip_comments(panels_text, keep_lines=True).split("\n")

    def fn_end(ranges: dict[int, int], line: int) -> int:
        end = ranges.get(line)
        if end is None:
            fail(f"no function starts at line {line} of a parameter panel file")
        return end

    constructors = [
        (i, fn_end(edit_ranges, i))
        for i, line in enumerate(edit, 1)
        if _CONSTRUCTOR.match(line)
    ]
    # Named functions holding no constructor (not the file's enclosing ones).
    local_fns: dict[str, tuple[int, int]] = {}
    for i, line in enumerate(edit, 1):
        m = _LOCAL_FUNCTION.match(line)
        if m and i in edit_ranges:
            end = edit_ranges[i]
            if not any(i <= c <= end for c, _ in constructors):
                local_fns.setdefault(m.group(1), (i, end))
    panel_defs: list[tuple[str, int]] = [
        (m.group(1), i)
        for i, line in enumerate(panels, 1)
        if (m := _PANEL_DEF.match(line))
    ]
    panel_spans: dict[str, tuple[int, int]] = {}
    for n, (name, start) in enumerate(panel_defs):
        end = len(panels)
        for j in range(start, len(panels)):
            if panels[j].startswith("end") or (
                n + 1 < len(panel_defs) and j + 1 >= panel_defs[n + 1][1]
            ):
                end = j
                break
        panel_spans.setdefault(name, (start, end))

    def refs(
        text_lines: list[str], first: int, last: int, in_panels: bool
    ) -> tuple[set[str], set[str], set[str]]:
        body = "\n".join(text_lines[first - 1 : last])
        params = set(_PARAM_REF.findall(body))
        used_panels = set(_PANEL_REF.findall(body))
        if in_panels:
            used_panels |= {p for p in _PANEL_CREATE.findall(body) if p in panel_spans}
        calls = (
            set() if in_panels else {c for c in _CALL.findall(body) if c in local_fns}
        )
        return params, used_panels, calls

    out: dict[str, list[str]] = {}
    for i, line in enumerate(edit, 1):
        m = _CONSTRUCTOR.match(line)
        if not m:
            continue
        params: set[str] = set()
        todo: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        p, ps, cs = refs(edit, i, fn_end(edit_ranges, i), False)
        params |= p
        todo += [("panel", x) for x in ps] + [("fn", x) for x in cs]
        while todo:
            item = todo.pop()
            if item in seen:
                continue
            seen.add(item)
            kind, name = item
            if kind == "fn":
                first, last = local_fns[name]
                p, ps, cs = refs(edit, first, last, False)
            elif name in panel_spans:
                first, last = panel_spans[name]
                p, ps, cs = refs(panels, first, last, True)
            else:
                continue
            params |= p
            todo += [("panel", x) for x in ps] + [("fn", x) for x in cs]
        out.setdefault(m.group(1), [])
        out[m.group(1)] = sorted(set(out[m.group(1)]) | params)
    return out
