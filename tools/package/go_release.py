"""Cut the Go module's release commit and tags.

The Go module's generated files (``types_gen.go``, ``series_gen.go``,
``series_gen_test.go`` and the gzipped bundles in ``data/``) are gitignored on
main, but ``go get`` fetches a module from a tag. A release therefore commits
HEAD's tree plus the generated files, with HEAD as its only parent, on no
branch, and tags it ``v<version>`` and ``packages/go/v<version>`` (the Go
subdirectory module tag).

Run after ``tools.package.go_package`` (``task package:go-release``).
``--dry-run`` changes nothing; ``--push`` pushes the two tags (CD does this
when it cuts a release).

    uv run python -m tools.package.go_release [--tag vX.Y.Z] [--dry-run] [--push]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from tools.datamine.common import REPO_ROOT, fail

from .go_package import GO_DIR

GO_TAG_PREFIX = "packages/go/"
GENERATED_FILES = ("types_gen.go", "series_gen.go", "series_gen_test.go")


def _git(*args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def _tag_exists(tag: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
            cwd=REPO_ROOT,
            capture_output=True,
        ).returncode
        == 0
    )


def generated_files() -> list[Path]:
    """The generated Go files, repository-relative, sorted."""
    files = [GO_DIR / n for n in GENERATED_FILES]
    data = sorted(p for p in (GO_DIR / "data").rglob("*") if p.is_file())
    missing = [p for p in files if not p.is_file()]
    if missing or not data:
        fail(
            f"generated Go files missing ({', '.join(p.name for p in missing) or 'data/'});"
            " run `task package:go` first"
        )
    return [p.relative_to(REPO_ROOT) for p in [*files, *data]]


def release_commit(files: list[Path], message: str) -> str:
    """A commit of HEAD's tree plus ``files`` (force-added past .gitignore)
    whose parent is HEAD, made in a scratch index: the work tree, the index
    and every branch are left as they were."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git("read-tree", "HEAD", env=env)
        _git("add", "--force", "--", *map(str, files), env=env)
        tree = _git("write-tree", env=env)
    return _git("commit-tree", tree, "-p", "HEAD", "-m", message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--tag",
        help="release tag (default: v<VERSION>); the Go tag is packages/go/<tag>",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would be committed and tagged"
    )
    parser.add_argument("--push", action="store_true", help="push both tags to origin")
    args = parser.parse_args()
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    tag = args.tag or f"v{version}"
    if not tag.startswith("v"):
        fail(f"release tag {tag!r} must start with 'v' (Go semantic version)")
    tags = [tag, GO_TAG_PREFIX + tag]
    existing = [t for t in tags if _tag_exists(t)]
    if existing and not args.dry_run:
        fail(f"tag(s) already exist: {', '.join(existing)}")
    files = generated_files()
    head = _git("rev-parse", "HEAD")
    size = sum((REPO_ROOT / f).stat().st_size for f in files)
    print(f"Release commit on {head[:12]} (parent; no branch moves), adding:")
    for f in files:
        print(f"  {f.as_posix()}  {(REPO_ROOT / f).stat().st_size:,} B")
    print(f"  {len(files)} files, {size:,} B")
    print(f"Tags: {', '.join(tags)}")
    if args.dry_run:
        if existing:
            print(f"Would refuse: tag(s) already exist: {', '.join(existing)}")
        print("Dry run: nothing committed, tagged or pushed.")
        return 0
    commit = release_commit(
        files, f"chore(release): {tag} with the generated Go module"
    )
    for t in tags:
        _git("tag", t, commit)
    print(f"Tagged {commit[:12]}: {', '.join(tags)}")
    if args.push:
        _git("push", "--atomic", "origin", *(f"refs/tags/{t}" for t in tags))
        print("Pushed the tags to origin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
