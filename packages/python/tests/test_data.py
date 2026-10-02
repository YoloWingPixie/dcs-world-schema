"""Every bundle loads and every record matches its TypedDict: no unknown keys,
required keys present, values of the annotated types (recursively)."""

from __future__ import annotations

import typing
from collections.abc import Mapping
from typing import Any, Literal, NotRequired, Union, get_args, get_origin

import dcs_world_reference as ref
import pytest
from dcs_world_reference import entities


def _errors(value: Any, tp: Any, path: str) -> list[str]:
    origin = get_origin(tp)
    if origin is NotRequired:
        return _errors(value, get_args(tp)[0], path)
    if origin is Union:
        branches = [_errors(value, t, path) for t in get_args(tp)]
        return [] if any(not b for b in branches) else min(branches, key=len)
    if origin is Literal:
        ok = value in get_args(tp) and not isinstance(value, bool)
        return [] if ok else [f"{path}: {value!r} not in {get_args(tp)}"]
    if origin is list:
        if not isinstance(value, list):
            return [f"{path}: expected a list, got {type(value).__name__}"]
        (item,) = get_args(tp)
        return [
            e for i, v in enumerate(value) for e in _errors(v, item, f"{path}[{i}]")
        ]
    if origin is dict:
        if not isinstance(value, dict):
            return [f"{path}: expected an object, got {type(value).__name__}"]
        _, item = get_args(tp)
        return [e for k, v in value.items() for e in _errors(v, item, f"{path}.{k}")]
    if typing.is_typeddict(tp):
        return _record_errors(value, tp, path)
    if tp is object:
        return []
    if tp is type(None):
        return [] if value is None else [f"{path}: expected null, got {value!r}"]
    if tp is float:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return [] if ok else [f"{path}: expected a number, got {value!r}"]
    if tp in (str, bool):
        ok = isinstance(value, tp)
        return [] if ok else [f"{path}: expected {tp.__name__}, got {value!r}"]
    raise TypeError(f"{path}: unsupported annotation {tp!r}")


def _record_errors(value: Any, td: Any, path: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path}: expected {td.__name__}, got {type(value).__name__}"]
    hints = typing.get_type_hints(td, vars(entities), include_extras=True)
    errors = [
        f"{path}: unknown key {k!r} for {td.__name__}" for k in value if k not in hints
    ]
    errors += [f"{path}: missing {k!r}" for k in td.__required_keys__ if k not in value]
    for k, v in value.items():
        if k in hints:
            errors += _errors(v, hints[k], f"{path}.{k}")
    return errors


def _record_type(name: str) -> Any:
    ret = typing.get_type_hints(getattr(ref, name))["return"]
    assert get_origin(ret) is Mapping
    return get_args(ret)[1]


def test_manifest() -> None:
    manifest = ref.manifest()
    assert _record_errors(manifest, entities.Provenance, "manifest") == []
    assert manifest["dcsVersion"] == ref.DCS_VERSION


@pytest.mark.parametrize("name", ref.SERIES)
def test_series(name: ref.SeriesName) -> None:
    records = getattr(ref, name)()
    assert records, f"{name}: no records"
    assert getattr(ref, name)() is records
    td = _record_type(name)
    key_field = ref.SERIES_KEYS[name]
    errors: list[str] = []
    for key, record in records.items():
        assert str(record[key_field]) == key
        errors += _record_errors(record, td, f"{name}[{key!r}]")
    assert errors == [], "\n".join(errors[:50])
