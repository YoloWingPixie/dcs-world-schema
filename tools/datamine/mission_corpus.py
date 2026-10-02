"""The AI actions DCS's own missions use: every ``.miz`` under the install
(campaigns, module missions, tutorials).

Each ``mission`` file runs in the datamine's Lua sandbox (no libraries, the
instruction limit); the walker visits every group's route waypoint tasks
(``route``) and its triggered actions (``group.tasks``, ``triggered``), through
``ComboTask``, ``ControlledTask`` and ``WrappedAction``, and keys each action
the way the Mission Editor does (``me_action_db.getActionKey``): an option by
``Option:<name>``, a wrapped command by its ``action.id``, any other task by
its ``key`` or else its ``id``. Per key: how often it occurs, in which group
categories and contexts (``route``/``triggered`` plus the wrapper chain), per
parameter the Lua types of its values and the string values (up to 64
characters) with their counts; per option name the values used.
Files run in worker processes; the merged counts do not depend on their order.
"""

from __future__ import annotations

import functools
import os
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import pmap
from .lua_reader import lua_execute, lua_to_py, sandbox_exec

CHUNK = 64
# Bumped when the merged counts change shape (the corpus cache key).
FORMAT = 2

WALKER = r"""
local MAX_STRING = 64
return function(env, acc)
  local m = env.mission
  if type(m) ~= 'table' then return 'no mission table' end
  local function bump(t, k) t[k] = (t[k] or 0) + 1 end
  local function note(key, cat, ctx, params)
    local a = acc.actions[key]
    if not a then
      a = { count = 0, categories = {}, contexts = {}, params = {}, strings = {} }
      acc.actions[key] = a
    end
    a.count = a.count + 1
    bump(a.categories, cat)
    bump(a.contexts, ctx)
    if type(params) == 'table' then
      for k, v in pairs(params) do
        if type(k) == 'string' then
          a.params[k] = a.params[k] or {}
          bump(a.params[k], type(v))
          if type(v) == 'string' and #v <= MAX_STRING then
            a.strings[k] = a.strings[k] or {}
            bump(a.strings[k], v)
          end
        end
      end
    end
  end
  local walk
  walk = function(t, cat, ctx)
    if type(t) ~= 'table' then return end
    local id, p = t.id, t.params
    if id == 'ComboTask' and type(p) == 'table' and type(p.tasks) == 'table' then
      for _, s in pairs(p.tasks) do walk(s, cat, ctx .. '>ComboTask') end
      return
    end
    if id == 'ControlledTask' and type(p) == 'table' then
      walk(p.task, cat, ctx .. '>ControlledTask')
      return
    end
    if id == 'WrappedAction' and type(p) == 'table' and type(p.action) == 'table' then
      local a = p.action
      local ap = type(a.params) == 'table' and a.params or {}
      if a.id == 'Option' then
        local key = 'Option:' .. tostring(ap.name)
        note(key, cat, ctx .. '>WrappedAction', ap)
        local v = acc.optionValues[key] or {}
        acc.optionValues[key] = v
        bump(v, type(ap.value) .. ':' .. tostring(ap.value))
      else
        note(tostring(a.id), cat, ctx .. '>WrappedAction', ap)
      end
      return
    end
    if id ~= nil then
      note(tostring(t.key ~= nil and t.key or id), cat, ctx, p)
      if t.key ~= nil then bump(acc.keyed, tostring(id) .. '/' .. tostring(t.key)) end
    end
  end
  local cats = { 'plane', 'helicopter', 'vehicle', 'ship' }
  for _, side in pairs(type(m.coalition) == 'table' and m.coalition or {}) do
    for _, c in pairs(type(side) == 'table' and type(side.country) == 'table' and side.country or {}) do
      for _, cat in ipairs(cats) do
        local g = type(c) == 'table' and c[cat]
        for _, grp in pairs(type(g) == 'table' and type(g.group) == 'table' and g.group or {}) do
          if type(grp) == 'table' then
            local route = grp.route
            for _, wp in pairs(type(route) == 'table' and type(route.points) == 'table' and route.points or {}) do
              if type(wp) == 'table' then walk(wp.task, cat, 'route') end
            end
            for _, t in pairs(type(grp.tasks) == 'table' and grp.tasks or {}) do
              walk(t, cat, 'triggered')
            end
          end
        end
      end
    end
  end
  return 'ok'
end
"""


@dataclass
class Corpus:
    """Merged counts (``scan``)."""

    files: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    option_values: dict[str, Counter[str]] = field(default_factory=dict)
    keyed: Counter[str] = field(default_factory=Counter)

    def add(self, part: dict[str, Any]) -> None:
        for key, a in part.get("actions", {}).items():
            into = self.actions.setdefault(
                key,
                {
                    "count": 0,
                    "categories": Counter(),
                    "contexts": Counter(),
                    "params": {},
                    "strings": {},
                },
            )
            into["count"] += a["count"]
            into["categories"].update(a.get("categories") or {})
            into["contexts"].update(a.get("contexts") or {})
            for name, types in (a.get("params") or {}).items():
                into["params"].setdefault(name, Counter()).update(types)
            for name, values in (a.get("strings") or {}).items():
                into["strings"].setdefault(name, Counter()).update(values)
        for key, values in part.get("optionValues", {}).items():
            self.option_values.setdefault(key, Counter()).update(values)
        self.keyed.update(part.get("keyed") or {})


@functools.cache
def _walker() -> Any:
    return lua_execute(WALKER)


def _scan_chunk(paths: list[str]) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Worker: the merged counts of ``paths`` and the files that failed."""
    from .lua_reader import _lua

    runtime = _lua().runtime
    acc = runtime.table(
        actions=runtime.table(), optionValues=runtime.table(), keyed=runtime.table()
    )
    failed: list[tuple[str, str]] = []
    for p in paths:
        try:
            with zipfile.ZipFile(p) as z:
                text = z.read("mission").decode("utf-8", "replace")
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            failed.append((p, f"unreadable: {exc}"))
            continue
        ok, env = sandbox_exec(text, Path(p).name)
        if not ok:
            failed.append((p, str(env)[:200]))
            continue
        status = _walker()(env, acc)
        if status != "ok":
            failed.append((p, str(status)))
    part = lua_to_py(acc)
    return {k: v if isinstance(v, dict) else {} for k, v in part.items()}, failed


def _entries(directory: str) -> tuple[list[str], list[str]]:
    """(``.miz`` files, subdirectories to descend) of ``directory``, as
    ``os.walk`` sees them: symlinked directories are not descended, an
    unreadable directory has none."""
    files: list[str] = []
    dirs: list[str] = []
    try:
        with os.scandir(directory) as it:
            for e in it:
                try:
                    is_dir = e.is_dir()
                except OSError:
                    is_dir = False
                if is_dir:
                    if not e.is_symlink():
                        dirs.append(e.path)
                elif e.name.lower().endswith(".miz"):
                    files.append(e.path)
    except OSError:
        pass
    return files, dirs


def mission_files(install_dir: Path) -> list[Path]:
    """Every ``.miz`` under the install, sorted; each directory level is
    listed on the I/O pool."""
    found: list[str] = []
    level = [str(install_dir)]
    while level:
        below: list[str] = []
        for files, dirs in pmap(_entries, level):
            found += files
            below += dirs
        level = below
    paths = [Path(p) for p in found]
    return sorted(paths, key=lambda p: str(p.relative_to(install_dir)).lower())


def scan(install_dir: Path, workers: int | None = None) -> Corpus:
    """The merged counts of every install mission."""
    files = [str(p) for p in mission_files(install_dir)]
    chunks = [files[i : i + CHUNK] for i in range(0, len(files), CHUNK)]
    corpus = Corpus(files=len(files))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part, failed in pool.map(_scan_chunk, chunks):
            corpus.add(part)
            corpus.failed += failed
    corpus.failed = sorted(
        (str(Path(p).relative_to(install_dir)), why) for p, why in corpus.failed
    )
    return corpus
