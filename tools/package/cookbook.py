"""The fenced code snippets of ``docs/cookbook.md``, for the tests that run them.

A snippet belongs to the recipe (``## `` heading) above it; its id is the
heading's slug. ``python -m tools.package.cookbook`` lists them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tools.datamine.common import REPO_ROOT

COOKBOOK = REPO_ROOT / "docs" / "cookbook.md"
LANGUAGES = ("ts", "python", "lua", "sql")
_FENCE = re.compile(r"^```(\w*)\n(.*?)^```$", re.M | re.S)
_HEADING = re.compile(r"^## (.+)$", re.M)


@dataclass(frozen=True)
class Snippet:
    recipe: str  # slug of the recipe heading
    lang: str
    code: str

    @property
    def id(self) -> str:
        return f"{self.recipe}.{self.lang}"


def slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def snippets(path: Path = COOKBOOK) -> list[Snippet]:
    """Every snippet in a recipe written in one of ``LANGUAGES``."""
    text = path.read_text(encoding="utf-8")
    headings = [(m.start(), slug(m.group(1))) for m in _HEADING.finditer(text)]
    out = []
    for m in _FENCE.finditer(text):
        recipe = next((h for pos, h in reversed(headings) if pos < m.start()), None)
        if recipe is not None and m.group(1) in LANGUAGES:
            out.append(Snippet(recipe, m.group(1), m.group(2)))
    ids = [s.id for s in out]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"one snippet per language and recipe: {duplicates}")
    return out


if __name__ == "__main__":
    for s in snippets():
        print(s.id)
