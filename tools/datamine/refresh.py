"""Refresh ``dcs-world-reference`` from the installed DCS in one step.

1. Read the install's DCS version; fail if ``dcs-world-reference/latest/`` holds
   a newer one; stop if it holds this one (``--force`` re-extracts it), unless
   a terrain has no runtime dump for this version, the API dump is not cached
   for it (3b) or ``.datamine/_G`` holds it in an older dump format
   (``common.DUMP_FORMAT``).
2. Run DCS headless (dcs-headless, isolated ``DCS.datamine`` profile) with the
   ``_G`` dump hook until the dump's version marker appears, unless
   ``.datamine/_G`` already holds this version in the current dump format (and
   no ``--force``).
3. Copy the dump to ``.datamine/_G`` (the ``task datamine:extract`` input).
3b. Unless ``.datamine/api`` holds this version's API dump made with the
   current API hooks (``api_dump.CACHE``; always with ``--force``): run DCS
   headless with the ``api-dump.lua`` hook and an empty mission (on Caucasus,
   else the first installed terrain) until ``api/done`` appears, and cache the
   per-environment files there. An unavailable scripting or hooks env fails the
   refresh; server and export are reported and kept as ``unavailable``.
3c. For each installed terrain without ``.datamine/terrains/<theatre>.done``
   for this version and ``<theatre>.hook`` matching the current terrain hooks'
   hash (all with ``--force``): run DCS headless with the
   ``terrain-dump.lua`` hook and an empty mission on that terrain
   (``terrain_mission``) until ``<theatre>.done`` appears, and cache
   ``<theatre>.lua``, ``.hook`` and ``.done`` there. A terrain that fails stops the
   refresh before extraction (dcs-world-reference untouched); terrains already
   cached are kept, so a rerun resumes.
3d. Only with ``--probe``, unless ``.datamine/probe`` holds this version's
   complete probe from the current inputs (``api_probe.CACHE``; always with
   ``--force``): carry crashes from a leftover progress file into
   ``crashed.json`` (``api_probe.harvest``), plan the probe (API dump,
   ``probe/doNotCall``, ``probe/contextSamples``, crashes denied,
   ``probe_mission``), run DCS headless with ``api-probe.lua`` until
   ``probe/done``, and cache ``probe.json``. A run that crashes or hangs
   (dcs.log, or ``progress.tsv`` unchanged for ``--probe-stall`` s) restarts
   while it makes progress, up to ``--probe-restarts`` times, resuming after
   the function it died in (marked ``crashed``). Out of restarts, the refresh
   continues with the partial probe (the next ``--probe`` resumes it); no
   progress fails the refresh. On Ctrl+C or a signal it caches the partial
   probe, installs it in ``dcs-world-reference/latest/`` when that holds this
   version (``common.install_probe``) and stops.
3e. Only with ``--actions-probe``: extract the Mission Editor's AI actions
   (``extract_actions``, from the install and the cached ``_G``), plan the
   actions probe (``actions_probe``) and, unless ``.datamine/actions-probe``
   holds a complete run of that plan (``--force`` reruns it), run DCS headless
   with ``actions-probe.lua`` and the actions probe mission until
   ``actions-probe/done``, restarting after crashes or hangs as for 3d; each
   run's dcs.log is kept in ``.datamine/actions-probe/logs`` (the probe
   attributes its lines to steps). The document (``actions-probe.json``) is
   cached, partial or not; interrupted, it is also installed.
   ``--actions-probe-followup`` does the same for the follow-up plan
   (``actions_probe.FOLLOWUP``; ``.datamine/actions-probe-followup``,
   ``actions-probe-followup/done``, ``api/actions-probe-followup.json``),
   after the actions probe when both are given; each keeps its own progress.
   The actions are extracted once and reused by step 4.
4. Extract it (with the install's stock liveries, the cached terrain dumps
   and this version's actions probe), in memory.
5. Validate it as ``task validate-data`` does; on failure nothing is written.
6. Write it, with the API dump and probe files (``api/``,
   ``extract.api_version_files``; probes without a run of this version are
   carried forward from the previous ``latest``), to
   ``dcs-world-reference/latest/``, replacing the previous version's data
   (kept in git history), regenerate the generated types
   (``extract.publish_latest``), and print per-series counts against the
   previous version.

    task datamine -- [--force] [--probe [--probe-restarts N] [--probe-stall S]]
        [--actions-probe] [--actions-probe-followup] [--install-dir DIR]
        [--auth-from DIR]

``dcs_headless`` is not a project dependency; ``task datamine`` supplies it with
``uv run --with``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml
from dcs_headless import HeadlessError, Interrupted, run
from dcs_headless.paths import resolve

from tools.export_jsonschema import export
from tools.merge import merge_tree

from . import (
    actions_probe,
    api_dump,
    api_probe,
    extract_actions,
    probe_mission,
)
from .common import (
    CACHE_DIR,
    CACHED_G_DIR,
    DONE,
    DUMP_FORMAT,
    HOOK_DIR,
    LATEST,
    REFERENCE_DATA_DIR,
    REPO_ROOT,
    CacheState,
    ProbeCache,
    fail,
    hooks_hash,
    install_probe,
    install_version,
    latest_version,
    pmap,
    read_dump_format,
    read_marker,
    read_progress,
    read_version,
    series_records,
    tree_files,
    version_key,
    warn,
    write_latest,
)
from .dcs_constants import Constants, generated_schemas
from .extract import api_version_files, extract, publish_latest
from .extract_theatres import installed_theatres
from .terrain_mission import install_defaults, mission_files, write_miz
from .validate_data import validate

PROFILE = "DCS.datamine"
HOOKS = [HOOK_DIR / "dump-globals.lua", HOOK_DIR / "serialize.lua"]
TERRAIN_HOOKS = [HOOK_DIR / "terrain-dump.lua", HOOK_DIR / "serialize.lua"]
DUMP_REL = "DCS.Lua.Exporter/_G"
TERRAIN_REL = "DCS.Lua.Exporter/terrains"
RUN_OUT = CACHE_DIR / "run"
TERRAINS_CACHE = CACHE_DIR / "terrains"
MISSIONS_DIR = CACHE_DIR / "missions"
# A terrain load is slow; the stall window covers minutes without dcs.log output.
TERRAIN_TIMEOUT = 900
TERRAIN_STALL_TIMEOUT = 300
SCHEMA_DIR = REPO_ROOT / "dcs-world-schema"
API_CACHE = api_dump.CACHED_API_DIR
API_THEATRE = "Caucasus"
PROBE_CACHE = api_probe.CACHED_PROBE_DIR
PROBE_RUN = CACHE_DIR / "probe-run"
# Each probe call is logged, so the dcs.log stall window covers the map load or
# one hung call. A hang DCS keeps logging past is caught by progress.tsv (a line
# per call, plus a heartbeat) not growing for PROBE_STALL s. Each crash or hang
# costs a restart, hence many.
PROBE_TIMEOUT = 3600
PROBE_STALL_TIMEOUT = 300
PROBE_STALL = 60
PROBE_RESTARTS = 60
ACTIONS_PROBE = actions_probe.MAIN
ACTIONS_PROBE_FOLLOWUP = actions_probe.FOLLOWUP
# The Mission Editor's actions and options: (series, report lines).
ActionSeries = tuple[dict[str, dict[str, Any]], list[str]]


def api_cache() -> ProbeCache:
    return replace(api_dump.CACHE, dir=API_CACHE)


def probe_cache() -> ProbeCache:
    return replace(api_probe.CACHE, dir=PROBE_CACHE)


def cache_dump(src: Path, dest: Path) -> None:
    """Replace ``dest`` with a copy of ``src`` (files copied in parallel)."""
    partial = dest.with_name(dest.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    pairs = []
    for root, _dirs, files in os.walk(src):
        target = partial / Path(root).relative_to(src)
        target.mkdir(parents=True, exist_ok=True)
        pairs += [(Path(root, f), target / f) for f in files]
    list(pmap(lambda p: shutil.copyfile(*p), pairs))
    shutil.rmtree(dest, ignore_errors=True)
    partial.rename(dest)
    print(f"Cached {len(pairs)} dump files in {dest}")


def terrain_hook_hash() -> str:
    """SHA-256 of the terrain hooks' names and contents."""
    return hooks_hash(TERRAIN_HOOKS)


def stale_terrain(theatre: str, version: str, hook_hash: str) -> str | None:
    """Why ``theatre``'s cached dump must be redone, or None when it is current."""
    done = read_marker(TERRAINS_CACHE / f"{theatre}.done")
    if done is None:
        return "no cached dump"
    if done != version:
        return f"cached dump is DCS {done}"
    if read_marker(TERRAINS_CACHE / f"{theatre}.hook") != hook_hash:
        return "terrain hook changed since it was dumped"
    return None


def _run_dcs(label: str, args: argparse.Namespace, **kw: Any) -> Any:
    """``dcs_headless.run`` in the datamine profile; fails with ``label`` unless
    the run succeeds."""
    try:
        result = run(
            profile=PROFILE,
            install_dir=args.install_dir,
            auth_from=args.auth_from,
            **kw,
        )
    except HeadlessError as exc:
        fail(f"{label}: DCS run failed: {exc}")
    if not result.ok:
        fail(
            f"{label}: DCS run failed: {result.reason} (log: {result.log}; "
            f"cleanup errors: {result.cleanup_errors})"
        )
    return result


def run_terrain(
    theatre: str,
    version: str,
    hook_hash: str,
    defaults: dict[str, Any],
    profile: Path,
    args: argparse.Namespace,
) -> None:
    """Run DCS on ``theatre``'s empty mission with the terrain hook; cache the dump."""
    miz = MISSIONS_DIR / f"{theatre}.miz"
    write_miz(miz, mission_files(theatre, defaults))
    rel = f"{TERRAIN_REL}/{theatre}"
    print(f"Running DCS {version} headless on terrain {theatre} ...")
    result = _run_dcs(
        f"terrain {theatre} (nothing extracted; terrains cached so far are kept "
        f"in {TERRAINS_CACHE})",
        args,
        hooks=TERRAIN_HOOKS,
        mission=miz,
        out=RUN_OUT / "terrains" / theatre,
        wait_file=f"{rel}.done",
        fail_log="Terrain dump failed",
        timeout=TERRAIN_TIMEOUT,
        stall_timeout=TERRAIN_STALL_TIMEOUT,
    )
    marker = read_marker(profile / f"{rel}.done")
    if marker != version:
        fail(f"terrain {theatre}: dump is DCS {marker}, the install is {version}")
    TERRAINS_CACHE.mkdir(parents=True, exist_ok=True)
    (TERRAINS_CACHE / f"{theatre}.done").unlink(missing_ok=True)
    (TERRAINS_CACHE / f"{theatre}.hook").write_text(hook_hash, encoding="utf-8")
    for suffix in (".lua", ".done"):  # .done last: it marks the cache entry valid
        dest = TERRAINS_CACHE / f"{theatre}{suffix}"
        partial = dest.with_name(dest.name + ".partial")
        shutil.copyfile(profile / f"{rel}{suffix}", partial)
        partial.replace(dest)
    print(f"Cached terrain {theatre} ({result.elapsed_seconds} s)")


def run_api(
    theatre: str,
    version: str,
    hooks_hash: str,
    defaults: dict[str, Any],
    profile: Path,
    args: argparse.Namespace,
) -> None:
    """Run DCS on an empty mission with the API dump hook; cache its files."""
    miz = MISSIONS_DIR / f"api-{theatre}.miz"
    write_miz(miz, mission_files(theatre, defaults))
    print(f"Running DCS {version} headless for the API dump ({theatre}) ...")
    result = _run_dcs(
        f"API dump (nothing extracted; cache in {API_CACHE} untouched)",
        args,
        hooks=api_dump.API_HOOKS,
        mission=miz,
        out=RUN_OUT / "api",
        wait_file=f"{api_dump.API_REL}/{DONE}",
        fail_log="API dump failed",
        timeout=TERRAIN_TIMEOUT,
        stall_timeout=TERRAIN_STALL_TIMEOUT,
    )
    src = profile / api_dump.API_REL
    marker = read_marker(src / DONE)
    if marker != version:
        fail(f"API dump is DCS {marker}, the install is {version}")
    report = {}
    for env in api_dump.ENVS:
        report[env] = api_dump.status(api_dump.load(src / f"{env}.json"))
        size = (src / f"{env}.json").stat().st_size
        print(f"  API env {env:<9} {report[env]} ({size // 1024} KiB)")
    failed = [e for e in api_dump.REQUIRED_ENVS if report[e] != "ok"]
    if failed:
        fail(f"API dump: {', '.join(failed)} unavailable (see above)")
    API_CACHE.mkdir(parents=True, exist_ok=True)
    (API_CACHE / DONE).unlink(missing_ok=True)
    (API_CACHE / api_dump.HOOK_STAMP).write_text(hooks_hash, encoding="utf-8")
    (API_CACHE / api_dump.STATES_FILE).unlink(missing_ok=True)
    names = [f"{env}.json" for env in api_dump.ENVS]
    if (src / api_dump.STATES_FILE).is_file():
        names.append(api_dump.STATES_FILE)
    for name in [*names, DONE]:
        dest = API_CACHE / name  # done last: it marks the cache valid
        partial = dest.with_name(dest.name + ".partial")
        shutil.copyfile(src / name, partial)
        partial.replace(dest)
    print(f"Cached the API dump ({result.elapsed_seconds} s)")


def progress_watch(
    progress: Path, stall: float, clock: Callable[[], float] = time.monotonic
) -> Callable[[], str | None]:
    """A run watch: the reason to end the run once ``progress`` has changed
    (size or mtime) since the watch was made and then not for ``stall``
    seconds, else None."""

    def stat() -> tuple[int, int] | None:
        try:
            st = progress.stat()
        except FileNotFoundError:
            return None
        return st.st_size, st.st_mtime_ns

    state: dict[str, Any] = {"seen": stat(), "changed": None}

    def check() -> str | None:
        now, seen = clock(), stat()
        if seen != state["seen"]:
            state["seen"], state["changed"] = seen, now
        elif state["changed"] is not None and now - state["changed"] >= stall:
            return f"{progress.name} stalled: unchanged for {stall:g}s"
        return None

    return check


@contextmanager
def watching(check: Callable[[], str | None]) -> Iterator[None]:
    """Make ``dcs_headless.run`` also end its run when ``check`` gives a
    reason: its wait loop (``runner.wait_for``) polls a ``watch`` every few
    seconds and fails the run on a reason, and ``run`` passes it only its
    process check, so ``wait_for`` is wrapped to poll both."""
    try:
        from dcs_headless import runner
    except ImportError:
        yield
        return
    wait_for = runner.wait_for

    def wait_for_watching(
        *, watch: Callable[[], str | None] | None = None, **kw: Any
    ) -> Any:
        def both() -> str | None:
            return (watch() if watch else None) or check()

        return wait_for(watch=both, **kw)

    runner.wait_for = wait_for_watching
    try:
        yield
    finally:
        runner.wait_for = wait_for


@dataclass
class ProbeRun:
    """One probe's DCS runs: ``hooks`` and ``miz`` until ``<out_rel>/done``,
    ``total`` ``unit`` recorded in ``progress`` (``recorded``); ``save``
    caches its document (partial or not) in ``cache``, ``install`` puts one
    in ``latest`` when that is its version, ``keep_log`` keeps a run's dcs.log."""

    name: str
    flag: str
    unit: str
    version: str
    total: int
    hooks: list[Path]
    miz: Path
    out: Path
    out_rel: str
    fail_log: str
    progress: Path
    recorded: Callable[[], int]
    save: Callable[[], dict[str, Any]]
    install: Callable[[dict[str, Any]], Path | None]
    cache: Path
    keep_log: Callable[[], None] = lambda: None


def run_probe_runs(
    r: ProbeRun, profile: Path, args: argparse.Namespace
) -> dict[str, Any]:
    """Run DCS for a probe until it finishes, restarting while each run makes
    progress, up to ``--probe-restarts`` times; its saved document. Without
    progress it fails; interrupted, it installs the partial document and
    stops the refresh; a complete run's done marker must be the version."""
    try:
        for attempt in range(args.probe_restarts + 1):
            before = r.recorded()
            print(
                f"Running DCS {r.version} headless for the {r.name} ({before} of "
                f"{r.total} {r.unit} recorded) ..."
            )
            try:
                with watching(progress_watch(r.progress, args.probe_stall)):
                    result = run(
                        profile=PROFILE,
                        install_dir=args.install_dir,
                        auth_from=args.auth_from,
                        hooks=r.hooks,
                        mission=r.miz,
                        out=r.out,
                        wait_file=f"{r.out_rel}/{DONE}",
                        fail_log=r.fail_log,
                        timeout=PROBE_TIMEOUT,
                        stall_timeout=PROBE_STALL_TIMEOUT,
                    )
            except HeadlessError as exc:
                r.keep_log()
                r.save()
                fail(f"{r.name}: DCS run failed: {exc}")
            r.keep_log()
            if result.ok:
                break
            after = r.recorded()
            if after <= before:
                r.save()
                fail(
                    f"{r.name}: DCS run failed without progress: {result.reason} "
                    f"(log: {result.log}; cleanup errors: {result.cleanup_errors})"
                )
            if attempt == args.probe_restarts:
                break
            print(
                f"  DCS run ended ({result.reason}) at {after} of {r.total}; "
                f"restarting ({attempt + 1}/{args.probe_restarts})"
            )
    except (Interrupted, KeyboardInterrupt):
        r.keep_log()
        doc = r.save()
        ver_dir = r.install(doc)
        warn(
            f"{r.name} interrupted at {r.recorded()} of {r.total} {r.unit}; cached "
            f"the partial probe in {r.cache}"
            + (f" and installed it in {ver_dir}" if ver_dir else "")
            + f" (rerun with {r.flag} to resume)"
        )
        raise SystemExit(130) from None
    doc = r.save()
    if doc["stats"]["complete"]:
        marker = read_marker(profile / r.out_rel / DONE)
        if marker != r.version:
            fail(f"{r.name} is DCS {marker}, the install is {r.version}")
    else:
        warn(
            f"{r.name}: {r.recorded()} of {r.total} {r.unit} after "
            f"{args.probe_restarts + 1} runs; keeping the partial probe (rerun "
            f"with {r.flag} to resume)"
        )
    return doc


def run_probe(
    version: str,
    inputs: str,
    defaults: dict[str, Any],
    profile: Path,
    args: argparse.Namespace,
) -> None:
    """Run the argument probe until it finishes, restarting DCS while each run
    makes progress; cache its probe.json, partial or not."""
    deny = api_probe.deny_list(version)
    progress = profile / api_probe.PROBE_REL / api_probe.PROGRESS
    plan_file = PROBE_RUN / api_probe.PLAN_NAME
    if progress.is_file():
        added = api_probe.harvest(
            PROBE_CACHE,
            read_progress(progress),
            version,
            plan_file.read_text(encoding="utf-8") if plan_file.is_file() else None,
        )
        for c in added:
            print(
                f"  carrying forward {c['env']} {c['path']}: crashed in plan {c['plan']}"
            )
    spec = probe_mission.spec(version)
    mission = probe_mission.build(spec, defaults)
    plan = api_probe.plan(
        API_CACHE,
        deny,
        version,
        mission=mission,
        rules=api_probe.context_rules(version),
        carried=api_probe.carried_crashes(PROBE_CACHE, version),
    )
    for line in api_probe.summary(plan, deny):
        print(line)
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(api_probe.plan_lua(plan), encoding="utf-8")
    miz = MISSIONS_DIR / f"probe-{spec['theatre']}.miz"
    write_miz(miz, mission.files)
    if args.force:  # else a progress file of this plan is resumed
        progress.unlink(missing_ok=True)
    store = probe_cache()

    def save() -> dict[str, Any]:
        doc = api_probe.document(plan, read_progress(progress))
        store.write(doc, version, inputs)
        return doc

    doc = run_probe_runs(
        ProbeRun(
            name="argument probe",
            flag="--probe",
            unit="functions",
            version=version,
            total=len(plan["entries"]),
            hooks=[*api_probe.PROBE_HOOKS, plan_file],
            miz=miz,
            out=RUN_OUT / "probe",
            out_rel=api_probe.PROBE_REL,
            fail_log="API probe failed",
            progress=progress,
            recorded=lambda: api_probe.recorded(progress, plan["id"]),
            save=save,
            install=lambda d: install_probe(d, store.file, REFERENCE_DATA_DIR),
            cache=PROBE_CACHE,
        ),
        profile,
        args,
    )
    api_probe.print_stats(doc)
    print(f"Cached the argument probe in {PROBE_CACHE}")


def action_records(install: Path) -> ActionSeries:
    """The install's Mission Editor actions and options (``extract_actions``,
    with the cached ``_G``); the report is printed."""
    built = extract_actions.build(install, CACHED_G_DIR)
    for line in built[1]:
        (warn if line.startswith("problem:") else print)(line.removeprefix("problem: "))
    return built


def run_actions_probe(
    probe: actions_probe.Probe,
    p: dict[str, Any],
    defaults: dict[str, Any],
    profile: Path,
    args: argparse.Namespace,
) -> None:
    """Run ``probe`` (the actions probe or its follow-up) with plan ``p`` until
    it finishes, restarting DCS while each run makes progress; cache its
    document, partial or not."""
    version = p["version"]
    store = probe.store
    progress = profile / probe.out_rel / actions_probe.PROGRESS
    plan_file = probe.run_dir / actions_probe.PLAN_NAME
    lib_file = probe.run_dir / actions_probe.LIB_NAME
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(actions_probe.plan_lua(p, probe.out_rel), encoding="utf-8")
    lib_file.write_text(probe.lib_lua(), encoding="utf-8")
    spec = probe_mission.spec(version)
    miz = MISSIONS_DIR / f"{probe.stem}-{spec['theatre']}.miz"
    write_miz(miz, actions_probe.mission(p, spec, defaults).files)
    logs = probe.cache / actions_probe.LOGS
    if args.force or store.status(version, p["id"])[0] is not CacheState.PARTIAL:
        progress.unlink(missing_ok=True)
        shutil.rmtree(logs, ignore_errors=True)
    measures = actions_probe.spec(version)["measures"]

    def save() -> dict[str, Any]:
        doc = actions_probe.document(
            p,
            read_progress(progress),
            actions_probe.cached_logs(probe.cache),
            measures,
            probe.format,
        )
        store.write(doc, version, doc["plan"])
        return doc

    def keep_log() -> None:
        log = RUN_OUT / "actions-probe" / "dcs.log"
        if log.is_file():
            logs.mkdir(parents=True, exist_ok=True)
            n = len(list(logs.glob("*.log"))) + 1
            shutil.copyfile(log, logs / f"run-{n:03d}.log")

    doc = run_probe_runs(
        ProbeRun(
            name=probe.name,
            flag=probe.flag,
            unit="steps",
            version=version,
            total=len(p["steps"]),
            hooks=[actions_probe.HOOK, actions_probe.JSON_LIB, lib_file, plan_file],
            miz=miz,
            out=RUN_OUT / "actions-probe",
            out_rel=probe.out_rel,
            fail_log="Actions probe failed",
            progress=progress,
            recorded=lambda: actions_probe.recorded(progress, p["id"]),
            save=save,
            install=lambda d: install_probe(d, probe.file, REFERENCE_DATA_DIR),
            cache=probe.cache,
            keep_log=keep_log,
        ),
        profile,
        args,
    )
    actions_probe.print_stats(doc)
    print(f"Cached the {probe.name} in {probe.cache}")


def api_theatre(theatres: list[str]) -> str:
    """The API dump mission's terrain: Caucasus (in every install) unless the
    install lists terrains without it."""
    if API_THEATRE in theatres or not theatres:
        return API_THEATRE
    return sorted(theatres)[0]


def counts(ver_dir: Path) -> dict[str, int]:
    return {n: len(r) for n, r in series_records(tree_files(ver_dir)).items()}


def entity_schema(constants: Constants) -> dict[str, Any]:
    """The entity JSON Schema with this extraction's generated constant enums."""
    merged, _ = merge_tree(str(SCHEMA_DIR))
    for text in generated_schemas(constants).values():
        merged["types"].update(yaml.safe_load(text)["types"])
    return export(merged["types"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force", action="store_true", help="re-extract an existing version"
    )
    parser.add_argument(
        "--install-dir",
        default=None,
        help="DCS install (default: dcs-headless resolution)",
    )
    parser.add_argument(
        "--auth-from",
        default=None,
        help="your DCS Saved Games profile (default: dcs-headless resolution)",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="also run the Lua API argument probe (api_probe; off by default)",
    )
    parser.add_argument(
        "--actions-probe",
        action="store_true",
        help="also run the live AI actions probe (actions_probe; off by default)",
    )
    parser.add_argument(
        "--actions-probe-followup",
        action="store_true",
        help="also run the actions probe's follow-up plan (off by default)",
    )
    parser.add_argument(
        "--probe-restarts",
        type=int,
        default=PROBE_RESTARTS,
        help=f"DCS restarts the probe may take after crashes (default {PROBE_RESTARTS})",
    )
    parser.add_argument(
        "--probe-stall",
        type=float,
        default=PROBE_STALL,
        help="seconds progress.tsv may stay unchanged before a probe run counts "
        f"as hung (default {PROBE_STALL:g})",
    )
    args = parser.parse_args(argv)

    try:
        paths = resolve(
            install_dir=args.install_dir, auth_from=args.auth_from, profile=PROFILE
        )
    except HeadlessError as exc:
        fail(f"cannot resolve DCS paths: {exc}")
    version = install_version(paths.install)
    if version is None:
        fail(f"no version in {paths.install / 'autoupdate.cfg'}")
    latest = REFERENCE_DATA_DIR / LATEST
    current = latest_version(REFERENCE_DATA_DIR)
    if current is not None and version_key(current) > version_key(version):
        fail(f"the install is DCS {version}, older than {latest} (DCS {current})")
    theatres = installed_theatres(paths.install)
    hook_hash = terrain_hook_hash()
    missing = []
    for t in theatres:
        why = "--force" if args.force else stale_terrain(t, version, hook_hash)
        if why:
            print(f"Terrain {t}: dumping ({why})")
            missing.append(t)
    api_hash = api_dump.hook_hash()
    api_why = "--force" if args.force else api_cache().stale(version, api_hash)
    if api_why:
        print(f"API dump: dumping ({api_why})")
    probe_why, probe_inputs = None, ""
    if args.probe:
        probe_inputs = api_probe.inputs_hash(
            api_probe.deny_list(version),
            api_hash,
            api_probe.context_rules(version),
            probe_mission.spec(version),
        )
        probe_why = (
            "--force" if args.force else probe_cache().stale(version, probe_inputs)
        )
        if probe_why:
            print(f"Argument probe: probing ({probe_why})")
    g_state, g_why = (
        (CacheState.MISSING, "--force") if args.force else globals_status(version)
    )
    g_current = g_state is CacheState.CURRENT
    probes = [
        pr
        for pr, on in (
            (ACTIONS_PROBE, args.actions_probe),
            (ACTIONS_PROBE_FOLLOWUP, args.actions_probe_followup),
        )
        if on
    ]
    built: ActionSeries | None = None

    def actions_plan(pr: actions_probe.Probe) -> dict[str, Any]:
        nonlocal built
        if built is None:
            built = action_records(paths.install)
        return pr.plan(built[0]["actions"], built[0]["options"], version)

    actions_plans: dict[str, dict[str, Any]] = {}
    actions_whys: dict[str, str] = {}
    for pr in probes:
        if args.force:
            why = "--force"
        elif g_current:
            actions_plans[pr.name] = actions_plan(pr)
            why = pr.store.stale(version, actions_plans[pr.name]["id"])
        else:
            why = "its plan needs this version's _G dump"
        if why:
            actions_whys[pr.name] = why
            print(f"{pr.name.capitalize()}: probing ({why})")
    actions_why = bool(actions_whys)
    old_format = g_state is CacheState.INPUTS_CHANGED
    if old_format:
        print(f"_G dump: dumping ({g_why})")
    if (
        current == version
        and not args.force
        and not old_format
        and not missing
        and not api_why
        and not probe_why
        and not actions_why
    ):
        print(f"{latest} holds DCS {version}: already up to date (--force re-extracts)")
        return 0

    if not g_current:
        dump_globals(version, paths.profile, args)
    else:
        print(f"Reusing {CACHED_G_DIR} (DCS {version}; --force re-dumps)")
    defaults = (
        install_defaults(paths.install)
        if missing or api_why or probe_why or actions_why
        else {}
    )
    if api_why:
        run_api(api_theatre(theatres), version, api_hash, defaults, paths.profile, args)
    if probe_why:
        run_probe(version, probe_inputs, defaults, paths.profile, args)
    for pr in probes:
        if pr.name not in actions_whys:
            continue
        plan = actions_plans.get(pr.name) or actions_plan(pr)
        for line in actions_probe.summary(plan):
            print(line)
        if args.force or pr.store.stale(version, plan["id"]):
            run_actions_probe(pr, plan, defaults, paths.profile, args)
        else:
            print(f"{pr.name.capitalize()}: {pr.cache} holds this plan's complete run")
    for theatre in missing:
        run_terrain(theatre, version, hook_hash, defaults, paths.profile, args)

    before = counts(latest) if current else {}
    extraction = extract(
        CACHED_G_DIR,
        paths.install,
        TERRAINS_CACHE,
        actions_probe_doc=ACTIONS_PROBE.load(version, REFERENCE_DATA_DIR),
        actions=built,
    )
    files = extraction.files()
    print(f"\nValidating DCS {version}")
    if not validate(files, entity_schema(extraction.constants), version):
        fail(f"validation failed: DCS {version} was not written to {latest}")
    files = {
        **files,
        **api_version_files(
            version,
            paths.install,
            REFERENCE_DATA_DIR,
            API_CACHE,
            PROBE_CACHE,
            (ACTIONS_PROBE, ACTIONS_PROBE_FOLLOWUP),
        ),
    }
    write_latest(REFERENCE_DATA_DIR, files)
    print(f"Installed DCS {version} in {latest}")
    publish_latest(latest, extraction, CACHED_G_DIR)

    after = {n: len(r) for n, r in extraction.series.items()}
    label = current or "(none)"
    print(f"\n{'series':16s} {label:>14s} {version:>14s}")
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name, 0), after.get(name, 0)
        print(
            f"{name:16s} {old:14d} {new:14d}{'' if old == new else f'  ({new - old:+d})'}"
        )
    return 0


def globals_status(version: str) -> tuple[CacheState, str]:
    """Whether ``.datamine/_G`` holds ``version`` in the hook's dump format,
    and why not."""
    cached = read_version(CACHED_G_DIR)
    if cached is None:
        return CacheState.MISSING, "not cached"
    if cached != version:
        return CacheState.OTHER_VERSION, f"cached dump is DCS {cached}"
    fmt = read_dump_format(CACHED_G_DIR)
    if fmt != DUMP_FORMAT:
        what = "has no format marker" if fmt is None else f"is format {fmt}"
        return CacheState.INPUTS_CHANGED, (
            f"cached dump {what}, the hook writes {DUMP_FORMAT}"
        )
    return CacheState.CURRENT, f"cached dump is DCS {cached}"


def dump_globals(version: str, profile: Path, args: argparse.Namespace) -> None:
    """Run DCS with the ``_G`` dump hook and cache the dump in ``.datamine/_G``."""
    print(f"Running DCS {version} headless in {profile} ...")
    _run_dcs(
        "_G dump",
        args,
        hooks=HOOKS,
        out=RUN_OUT,
        wait_file=f"{DUMP_REL}/__DCS_VERSION__.lua",
        fail_log="Export aborted|records failed",
        timeout=600,
        stall_timeout=120,
    )

    dump = profile / DUMP_REL
    dumped = read_version(dump)
    if dumped != version:
        fail(f"dump at {dump} is version {dumped}, the install is {version}")
    if (fmt := read_dump_format(dump)) != DUMP_FORMAT:
        fail(f"dump at {dump} is format {fmt}, the extractors read {DUMP_FORMAT}")
    cache_dump(dump, CACHED_G_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
