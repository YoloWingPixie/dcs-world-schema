"""Generate ``dcs-world-schema/types/ai/*.generated.yaml``: the AI task,
en-route task, command and option table types keyed by DCS's own ids, from
the ``actions`` and ``options`` series (``extract_actions``) of
``dcs-world-reference/latest``.

Types live in the ``DcsTask`` namespace and are the schema's task, en-route
task, command and option tables (``Controller.setTask`` and friends); the
live actions probe (``api/actions-probe.json``) showed the engine takes only
these ids, in DCS casing:

* per task, en-route task and command id: ``DcsTask.<Kind>.<dcsId>`` (``id``,
  typed as the literal id so another casing is a type error; ``key`` when the
  Mission Editor has keyed variants; ``params``) and
  ``DcsTask.<Kind>.<dcsId>Params`` (every parameter name the series has, all
  optional; typed by the Lua types seen, ``any`` when only named in the source);
* ``DcsTask.Any<Kind>`` (union), ``DcsTask.<Kind>Id`` (enum of the ids);
* ``DcsTask.OptionName`` (enum of the option numbers), one
  ``DcsTask.OptionValue.<OPTION>`` enum per value list (suffixed with its
  categories when an option has one per category; plus the values of the
  scripting API's ``AI.Option`` table the list lacks; ``FORMATION`` values
  encoded from the ``formations`` series), ``DcsTask.Option`` and
  ``DcsTask.WrappedAction``.

The ids and parameters are the series' alone (a pure function of its
records): the Mission Editor's, those of DCS's own scripts, and parameters
``overlays.yaml`` record patches add (``_source`` hand-authored, described
as such). Descriptions come from the Mission Editor's text and the series'
evidence, plus the optional hand-written text overlay ``actions/descriptions``
in ``overlays.yaml`` (``{kind: {dcsId: {description, params: {name:
text}}}}``; options by ``OptionName``): ``params`` text, or ``{type,
description}`` to name a schema type for one; ``param: {name: type}`` types
a parameter name in every action without its own type. An entry for an id
or a parameter name the series lacks is an error. Where a params record has
both ``point`` and ``x``/``y``, each says the forms are alternatives.

    uv run python -m tools.datamine.action_types [--data-dir DIR] [--out DIR] [--check]
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any, cast

import yaml

from . import overlays as overlays_mod
from .api_dump import legacy, scalars_at
from .common import (
    API_DIR,
    HAND_AUTHORED,
    LATEST,
    MANIFEST,
    REFERENCE_DATA_DIR,
    REPO_ROOT,
    fail,
    generated_drift,
    load_json,
    load_series,
    write_generated,
)
from .overlays import unused_keys

OUT_DIR = REPO_ROOT / "dcs-world-schema" / "types" / "ai"
SUFFIX = ".generated.yaml"
NS = "DcsTask"
SERIES, TABLE = "actions", "descriptions"
KIND_TYPES = {
    "task": ("Task", "Tasks"),
    "enrouteTask": ("EnrouteTask", "EnrouteTasks"),
    "command": ("Command", "Commands"),
}
KIND_TEXT = {"task": "task", "enrouteTask": "en-route task", "command": "command"}
_LUA_TYPES = {
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "table": "table",
}
_ENUM_KEY = re.compile(r"[^A-Za-z0-9]+")


def descriptions(version: str | None = None) -> dict[str, Any]:
    """The ``actions/descriptions`` overlay (empty when there is none)."""
    facts = overlays_mod.load(version)
    if (SERIES, TABLE) not in facts.tables:
        return {}
    return cast(dict[str, Any], facts.table(SERIES, TABLE))


def _q(text: str) -> str:
    return text.replace("\n", " ").strip()


def _type(types: list[str]) -> str:
    mapped = sorted({_LUA_TYPES[t] for t in types if t in _LUA_TYPES})
    return " | ".join(mapped) if mapped else "any"


def _value_text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return "a table"
    return f"`{v}`" if not isinstance(v, str) else f'`"{v}"`'


def _param_description(
    name: str, variants: list[dict[str, Any]], hand: str | None
) -> str:
    sources: list[str] = []
    defaults: list[str] = []
    strings: Counter[str] = Counter()
    missions = 0
    hand_authored = False
    for a in variants:
        p = next((p for p in a["params"] if p["name"] == name), None)
        if p is None:
            continue
        stamp = (a.get("_source") or {}).get(f"params[name={name}]")
        hand_authored = hand_authored or stamp == HAND_AUTHORED
        sources += [s for s in p["seenIn"] if s not in sources]
        missions += p.get("missionCount", 0)
        for v in p.get("missionStrings") or []:
            strings[v["value"]] += v["count"]
        if name in (a.get("defaultParams") or {}):
            text = _value_text(a["defaultParams"][name])
            label = f"{text} ({a['id']})" if len(variants) > 1 else text
            if label not in defaults:
                defaults.append(label)
    total = sum((a.get("missions") or {}).get("count", 0) for a in variants)
    parts = [hand.strip()] if hand else []
    if sources:
        parts.append(f"Seen in: {', '.join(sources)}.")
    if hand_authored:
        parts.append(
            "Hand-authored (overlays.yaml): in no Mission Editor default or "
            "source, DCS script or install mission."
        )
    if defaults:
        parts.append(f"Mission Editor default: {', '.join(defaults)}.")
    if missions:
        parts.append(f"Set by {missions} of {total} install mission uses.")
    if strings:
        listed = ", ".join(
            f'`"{v}"` ({n})'
            for v, n in sorted(strings.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        parts.append(f"Install mission values: {listed}.")
    return " ".join(parts)


def _id_field(dcs_id: str) -> dict[str, str]:
    """The ``id`` field of an action table: the literal DCS id, so another
    casing is a type error."""
    return {"type": f'"{dcs_id}"', "description": f'Always `"{dcs_id}"` (DCS casing).'}


POINT_FORMS = (
    "Either `point` or `x`/`y`; which one DCS reads is unconfirmed (the Mission "
    "Editor writes `x`/`y`)."
)


def _point_forms(fields: dict[str, Any]) -> None:
    """Note on ``point`` and ``x``/``y`` that they are alternatives."""
    if "point" in fields and {"x", "y"} <= set(fields):
        for n in ("point", "x", "y"):
            fields[n]["description"] = f"{fields[n]['description']} {POINT_FORMS}"


def _record(
    description: str, fields: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "kind": "record",
        "description": description,
        "fields": fields,
        "required": required,
    }


def _params(
    kind: str,
    dcs_id: str,
    variants: list[dict[str, Any]],
    hand_params: dict[str, Any],
    by_name: dict[str, str],
    used_names: set[str],
) -> dict[str, Any]:
    """The params record fields of an id: every parameter name of its
    variants."""
    names = sorted({p["name"] for a in variants for p in a["params"]})
    stale = sorted(set(hand_params) - set(names))
    if stale:
        fail(
            f"overlays {SERIES}/{TABLE} {kind} {dcs_id}: params {stale} are in no "
            "actions series record"
        )
    param_fields = {}
    for n in names:
        seen = [
            t
            for a in variants
            for p in a["params"]
            if p["name"] == n
            for t in p["types"]
        ]
        h = hand_params.get(n)
        named = None
        if isinstance(h, dict):
            named = h["type"]
            h = h.get("description")
        elif n in by_name:
            named = by_name[n]
            used_names.add(n)
        param_fields[n] = {
            "type": named or _type(seen),
            "description": _param_description(n, variants, h),
        }
    _point_forms(param_fields)
    return param_fields


def _kind_types(
    kind: str,
    actions: list[dict[str, Any]],
    hand: dict[str, Any],
    used: set[str],
    by_name: dict[str, str],
    used_names: set[str],
) -> dict[str, Any]:
    short, _ = KIND_TYPES[kind]
    by_id: dict[str, list[dict[str, Any]]] = {}
    for a in actions:
        if a["kind"] == kind:
            by_id.setdefault(a["dcsId"], []).append(a)
    types: dict[str, Any] = {}
    record_names = []
    for dcs_id, variants in sorted(by_id.items()):
        entry = hand.get(dcs_id) or {}
        used.add(dcs_id)
        rec_name = f"{NS}.{short}.{dcs_id}"
        params_name = f"{rec_name}Params"
        record_names.append(rec_name)
        fields: dict[str, Any] = {"id": _id_field(dcs_id)}
        desc = []
        me = "; ".join(
            f"{a['id']}: {a['displayName']}"
            + (f" ({_q(a['description'])})" if a.get("description") else "")
            for a in variants
            if a["modules"]
        )
        if me:
            desc.append(
                f"The `{dcs_id}` {KIND_TEXT[kind]} as the Mission Editor writes it ({me})."
            )
        scripts = [
            f"{s.get('function') or s['file']} ({s['file']}, {s['call']})"
            for a in variants
            for s in a.get("scripts") or []
        ]
        if scripts:
            desc.append(
                f"{'Also sent' if me else 'Sent'} by DCS's scripts: {'; '.join(scripts)}."
            )
        keys = sorted({a["key"] for a in variants if a.get("key")})
        if keys:
            key_enum = f"{rec_name}Key"
            types[key_enum] = {
                "kind": "enum",
                "description": f"Mission Editor variant keys of `{dcs_id}`.",
                "values": {k: k for k in keys},
            }
            fields["key"] = {
                "type": key_enum,
                "description": "Optional Mission Editor variant key (the Mission Editor's own; "
                "whether DCS reads it is not known).",
            }
        param_fields = _params(
            kind, dcs_id, variants, entry.get("params") or {}, by_name, used_names
        )
        if entry.get("description"):
            desc.insert(0, entry["description"].strip())
        fields["params"] = {
            "type": params_name,
            "description": "Parameters; every one optional.",
        }
        types[rec_name] = _record(" ".join(desc), fields, ["id"])
        types[params_name] = _record(f"Parameters of `{dcs_id}`.", param_fields, [])
    types[f"{NS}.Any{short}"] = {
        "kind": "union",
        "description": f"Any {KIND_TEXT[kind]} table, by DCS id.",
        "anyOf": record_names,
    }
    types[f"{NS}.{short}Id"] = {
        "kind": "enum",
        "description": f"{KIND_TEXT[kind].capitalize()} ids as the Mission Editor writes them (DCS casing).",
        "values": {i: i for i in sorted(by_id)},
    }
    return types


def _enum_key(name: str | None, value: Any, taken: set[str]) -> str:
    key = _ENUM_KEY.sub("_", name or "").strip("_").upper()
    if not key or key[0].isdigit():
        key = f"VALUE_{str(value).upper()}"
    if key in taken:
        key = f"{key}_{str(value).upper()}"
    taken.add(key)
    return key


# Group categories -> the scripting API's ``AI.Option`` table of their options.
OPTION_TABLES = {
    "plane": "Air",
    "helicopter": "Air",
    "vehicle": "Ground",
    "ship": "Naval",
}
_PARENTHESISED = re.compile(r"\s*\(.*?\)")
# FORMATION values: formation index << 16 | side << 8 | variant
# (MissionEditor/modules/me_action_edit_panel.lua, recalcValue).
FORMATION_SIDES = (("RIGHT", 0), ("LEFT", 1))


def _formation_values(
    world_ids: list[int], formations: dict[str, dict[str, Any]]
) -> dict[str, int]:
    """``{key: value}`` of each variant (and side) of the formations with
    ``world_ids``; a formation without a default variant also by itself."""
    by_world = {f["worldId"]: f for f in formations.values()}
    out: dict[str, int] = {}
    for wid in world_ids:
        f = by_world.get(wid)
        if f is None:
            fail(f"option FORMATION value {wid}: no formations series record")
        variants = [v.get("name") for v in f.get("variants") or []]
        sides = FORMATION_SIDES if f.get("zInverse") else (("", 0),)
        if f.get("defaultVariantIndex") is None:
            out[f["id"]] = wid << 16
        for i, name in enumerate(variants, 1):
            if not name:
                continue
            label = _ENUM_KEY.sub("_", _PARENTHESISED.sub("", name)).strip("_")
            for side, bit in sides:
                key = "_".join(k for k in (f["id"], label.upper(), side) if k)
                out[key] = wid << 16 | bit << 8 | i
    return out


def _runtime_extra(
    option: str, cats: list[str], runtime: dict[str, Any], listed: set[Any]
) -> dict[str, Any]:
    """``{name: value}`` of the scripting API's ``AI.Option.<table>.val.<option>``
    values for ``cats`` that the Mission Editor's list lacks."""
    out: dict[str, Any] = {}
    for table in sorted({OPTION_TABLES[c] for c in cats if c in OPTION_TABLES}):
        values = scalars_at(runtime, f"AI.Option.{table}.val.{option}") or {}
        for name, value in sorted(values.items(), key=lambda kv: (kv[1], kv[0])):
            if value not in listed and value not in out.values():
                out[name] = value
    return out


def option_value_type(option: dict[str, Any], value_set: dict[str, Any]) -> str:
    """The ``DcsTask.OptionValue.*`` enum of one of an option's value sets."""
    name = f"{NS}.OptionValue.{option['id']}"
    cats = value_set.get("categories")
    if len(option.get("valueSets") or []) > 1 and cats:
        name += "_" + "_".join(cats)
    return name


def _option_types(
    options: list[dict[str, Any]],
    hand: dict[str, Any],
    used: set[str],
    formations: dict[str, dict[str, Any]],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    types: dict[str, Any] = {}
    types[f"{NS}.OptionName"] = {
        "kind": "enum",
        "description": "AI option numbers (the Mission Editor's `OptionName`): "
        "`Controller.setOption` first argument, `params.name` of an `Option` action.",
        "values": {
            o["id"]: o["value"] for o in sorted(options, key=lambda o: o["value"])
        },
    }
    for o in sorted(options, key=lambda o: o["value"]):
        entry = hand.get(o["id"]) or {}
        used.add(o["id"])
        sets = o.get("valueSets") or []
        for s in sets:
            values = s.get("values")
            if not values:
                continue
            name = option_value_type(o, s)
            cats = s.get("categories")
            desc = [f"Values of option {o['id']} ({o['value']})"]
            if cats:
                desc.append(f"for {', '.join(cats)}")
            if o["id"] == "FORMATION":
                enum_values = _formation_values(
                    [v["value"] for v in values], formations
                )
                text = " ".join(desc) + (
                    ": formation index << 16 | side (0 right, 1 left) << 8 | "
                    "variant, as the Mission Editor writes them; keys from the "
                    "formations series"
                )
            else:
                taken: set[str] = set()
                enum_values = {
                    _enum_key(v.get("name"), v["value"], taken): v["value"]
                    for v in values
                }
                text = " ".join(desc) + "; keys from the Mission Editor's display names"
                extra = _runtime_extra(
                    o["id"], cats or o["categories"], runtime, set(enum_values.values())
                )
                if extra:
                    text += (
                        "; also the scripting API's `AI.Option` values the "
                        f"Mission Editor does not list ({', '.join(extra)})"
                    )
                    for key, value in extra.items():
                        enum_values[_enum_key(key, value, taken)] = value
            if "default" in s:
                text += f"; Mission Editor default {_value_text(s['default'])}"
            if entry.get("description"):
                text = entry["description"].strip() + " " + text
            types[name] = {
                "kind": "enum",
                "description": text + ".",
                "values": enum_values,
            }
    types[f"{NS}.OptionParams"] = {
        "kind": "record",
        "description": "Parameters of an `Option` action.",
        "fields": {
            "name": {"type": f"{NS}.OptionName", "description": "Option number."},
            "value": {
                "type": "any",
                "description": f"Option value (`{NS}.OptionValue.*` for listed values).",
            },
        },
        "required": ["name"],
    }
    types[f"{NS}.Option"] = {
        "kind": "record",
        "description": "An option as the Mission Editor writes it (inside a `WrappedAction`).",
        "fields": {
            "id": _id_field("Option"),
            "params": {
                "type": f"{NS}.OptionParams",
                "description": "Option and value.",
            },
        },
        "required": ["id", "params"],
    }
    types[f"{NS}.WrappedActionParams"] = {
        "kind": "record",
        "description": "Parameters of a `WrappedAction`.",
        "fields": {
            "action": {
                "type": f"{NS}.AnyCommand | {NS}.Option",
                "description": "The wrapped command or option.",
            }
        },
        "required": ["action"],
    }
    types[f"{NS}.WrappedAction"] = {
        "kind": "record",
        "description": "A command or option as a task (how the Mission Editor stores them in a route).",
        "fields": {
            "id": _id_field("WrappedAction"),
            "params": {
                "type": f"{NS}.WrappedActionParams",
                "description": "The action.",
            },
        },
        "required": ["id", "params"],
    }
    return types


def _render(types: dict[str, Any], version: str, what: str) -> str:
    header = (
        f"# {what}, keyed by DCS's own ids, from the Mission Editor's action tables "
        f"(dcs-world-reference actions/options series).\n"
        f"# DCS version: {version}\n"
        "# Generated by tools/datamine/action_types.py; do not edit.\n"
    )
    body = yaml.safe_dump(
        {"globals": {}, "types": types},
        sort_keys=False,
        allow_unicode=True,
        width=100,
        default_flow_style=False,
    )
    return header + body


def generate(
    actions: dict[str, dict[str, Any]],
    options: dict[str, dict[str, Any]],
    version: str,
    hand: dict[str, Any] | None = None,
    formations: dict[str, dict[str, Any]] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, str]:
    """``{file name: text}`` for ``OUT_DIR`` from DCS ``version``'s
    ``actions``, ``options`` and ``formations`` records and its scripting API
    dump (``api_dump.legacy``); empty without actions."""
    if not actions:
        return {}
    hand = descriptions(version) if hand is None else hand
    unknown = set(hand) - {*KIND_TYPES, "option", "param"}
    if unknown:
        fail(f"overlays {SERIES}/{TABLE}: unknown kinds {sorted(unknown)}")
    by_name: dict[str, str] = hand.get("param") or {}
    used_names: set[str] = set()
    files: dict[str, str] = {}
    for kind, (_, file_stem) in KIND_TYPES.items():
        used: set[str] = set()
        kind_hand = hand.get(kind) or {}
        types = _kind_types(
            kind, list(actions.values()), kind_hand, used, by_name, used_names
        )
        unused_keys(kind_hand, used, f"overlays {SERIES}/{TABLE} {kind}")
        files[f"{file_stem}{SUFFIX}"] = _render(
            types, version, f"AI {KIND_TEXT[kind]}s"
        )
    used = set()
    option_hand = hand.get("option") or {}
    files[f"Options{SUFFIX}"] = _render(
        _option_types(
            list(options.values()),
            option_hand,
            used,
            formations or {},
            runtime or {},
        ),
        version,
        "AI options",
    )
    unused_keys(option_hand, used, f"overlays {SERIES}/{TABLE} option")
    unused_keys(by_name, used_names, f"overlays {SERIES}/{TABLE} param")
    return files


def generate_from(data_dir: Path, hand: dict[str, Any] | None = None) -> dict[str, str]:
    """``generate`` of a data dir's series."""
    actions = load_series(data_dir, "actions")
    if not actions:
        return {}
    scripting = data_dir / API_DIR / "scripting.json"
    return generate(
        actions,
        load_series(data_dir, "options"),
        load_json(data_dir / MANIFEST)["dcsVersion"],
        hand,
        load_series(data_dir, "formations"),
        legacy(load_json(scripting)) if scripting.is_file() else None,
    )


def write(files: dict[str, str], out: Path = OUT_DIR) -> None:
    """Make the generated files under ``out`` exactly ``files``; nothing
    without files (no actions series)."""
    if files:
        write_generated(out, files, SUFFIX)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=REFERENCE_DATA_DIR / LATEST)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--check", action="store_true", help="fail on drift")
    args = parser.parse_args(argv)
    files = generate_from(args.data_dir)
    if not files:
        print(f"No actions series in {args.data_dir}: nothing to generate")
        return 0
    if args.check:
        stale = generated_drift(args.out, files, SUFFIX)
        if stale:
            fail(
                f"AI action types out of date ({', '.join(stale)}); run `task datamine:action-types`"
            )
        print(f"AI action types match {args.data_dir}")
        return 0
    write(files, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
