from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import write

from tools import validate
from tools.datamine import dcs_database_types as dbt
from tools.datamine.common import REPO_ROOT, generated_drift

KIND = dbt.Kind("DcsDb.T", "t", "Test")


def _dump(g: Path, records: dict[str, str], table: str = "t") -> None:
    for name, body in records.items():
        write(g / table / f"{name}.lua", f'_G["{table}"]["{name}"] = {body}')


def _types(g: Path, kinds: tuple[dbt.Kind, ...] = (KIND,)) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for text in dbt.generate(g, kinds).values():
        out.update(yaml.safe_load(text)["types"])
    return out


def test_field_types_and_presence(tmp_path: Path) -> None:
    _dump(tmp_path, {"A": '{ a = 1, b = "x" }', "B": "{ a = 2.5, c = true }"})
    t = _types(tmp_path)["DcsDb.T"]
    assert t["kind"] == "record"
    assert t["required"] == ["a"]
    assert {n: f["type"] for n, f in t["fields"].items()} == {
        "a": "number",
        "b": "string",
        "c": "boolean",
    }
    assert t["fields"]["b"]["description"] == "Present in 1 of 2 tables."
    assert t["description"].startswith("Inferred from 2 tables")


def test_arrays_sparse_arrays_and_nested_records(tmp_path: Path) -> None:
    _dump(
        tmp_path,
        {
            "A": "{ xs = { 1, 2 }, pts = { { x = 1 }, { x = 2, y = 3 } } }",
            "B": "{ xs = { [1] = 5, [3] = 6 } }",
        },
    )
    types = _types(tmp_path)
    fields = types["DcsDb.T"]["fields"]
    assert fields["xs"]["type"] == "number[]"
    assert fields["pts"]["type"] == "DcsDb.TPts[]"
    pts = types["DcsDb.TPts"]
    assert pts["required"] == ["x"]
    assert pts["fields"]["y"]["description"] == "Present in 1 of 2 tables."
    assert "`DcsDb.T.pts[]`" in pts["description"]


def test_mixed_table_is_its_array_or_its_record(tmp_path: Path) -> None:
    _dump(tmp_path, {"A": "{ ws = { n = 1, { a = 1 } } }"})
    types = _types(tmp_path)
    assert types["DcsDb.T"]["fields"]["ws"]["type"] == "DcsDb.TWsItem[] | DcsDb.TWs"
    ws = types["DcsDb.TWs"]
    assert list(ws["fields"]) == ["n"]
    assert "array entries in 1 of them: `DcsDb.TWsItem`" in ws["description"]
    assert list(types["DcsDb.TWsItem"]["fields"]) == ["a"]


def test_unions(tmp_path: Path) -> None:
    _dump(
        tmp_path,
        {
            "A": '{ v = 1, attr = { 4, 15, "Redacted" }, els = { "s", { k = 1 } } }',
            "B": '{ v = "one" }',
        },
    )
    types = _types(tmp_path)
    fields = types["DcsDb.T"]["fields"]
    assert fields["v"]["type"] == "number | string"
    assert "Observed as number (1), string (1)." in fields["v"]["description"]
    assert fields["attr"]["type"] == "DcsDb.NumberOrString[]"
    assert types["DcsDb.NumberOrString"]["anyOf"] == ["number", "string"]
    assert fields["els"]["type"] == "DcsDb.TElsEntry[]"
    assert types["DcsDb.TElsEntry"] == {
        "kind": "union",
        "description": "Array element at `DcsDb.T.els[]`. "
        "Observed as string (1), table (1).",
        "anyOf": ["string", "DcsDb.TEls"],
    }


def test_nested_arrays_get_a_list_type(tmp_path: Path) -> None:
    _dump(tmp_path, {"A": "{ freq = { { 1, 2 }, { 3, 4 } } }"})
    types = _types(tmp_path)
    assert types["DcsDb.T"]["fields"]["freq"]["type"] == "DcsDb.TFreq[]"
    assert types["DcsDb.TFreq"]["kind"] == "array"
    assert types["DcsDb.TFreq"]["arrayOf"] == "number"


def test_many_rare_keys_make_a_map(tmp_path: Path) -> None:
    n = dbt.MAP_MIN_KEYS
    _dump(
        tmp_path,
        {f"R{i}": f"{{ byName = {{ k{i} = {{ id = {i} }} }} }}" for i in range(n)},
    )
    types = _types(tmp_path)
    assert types["DcsDb.T"]["fields"]["byName"]["type"] == "map<DcsDb.TByName>"
    assert types["DcsDb.TByName"]["fields"]["id"]["type"] == "number"


def test_shared_fields_refs_and_identical_shapes_merge(tmp_path: Path) -> None:
    g = tmp_path
    _dump(g, {"W1": "{ mass = 1 }", "W2": '"_G/warheads/W1.lua"'}, "warheads")
    _dump(
        g,
        {
            "A": '{ warhead = "_G/warheads/W1.lua", fm = { L = 1 } }',
            "B": "{ warhead = { mass = 2 }, sub = { fm = { L = 2 } } }",
        },
        "bombs",
    )
    kinds = (
        dbt.Kind("DcsDb.Warhead", "warheads", "Weapons"),
        dbt.Kind("DcsDb.Bomb", "bombs", "Weapons"),
    )
    types = _types(g, kinds)
    bomb = types["DcsDb.Bomb"]["fields"]
    assert bomb["warhead"]["type"] == "DcsDb.Warhead"
    assert bomb["warhead"]["description"] == "Present in 2 of 2 tables."
    assert types["DcsDb.Warhead"]["description"].startswith("Inferred from 2 tables")
    assert bomb["fm"]["type"] == "DcsDb.BombFm"
    assert types["DcsDb.BombSub"]["fields"]["fm"]["type"] == "DcsDb.BombFm"
    assert "DcsDb.BombSubFm" not in types
    assert types["DcsDb.BombFm"]["description"].startswith("Inferred from 2 tables")


def test_odd_keys_round_trip_and_output_is_valid_schema(tmp_path: Path) -> None:
    _dump(
        tmp_path,
        {"A": '{ ["Ka-50"] = 1, ["on"] = true, [" x y"] = "s", ["{C-1}"] = 2 }'},
    )
    text = dbt.generate(tmp_path, (KIND,))["Test.generated.yaml"]
    types = yaml.safe_load(text)["types"]
    assert sorted(types["DcsDb.T"]["fields"]) == [" x y", "Ka-50", "on", "{C-1}"]
    schema = validate.load_schema(REPO_ROOT / validate.DEFAULT_SCHEMA_FILENAME)
    _, _, v_type = validate.build_validators(schema)
    for entry in types.values():
        assert not list(v_type.iter_errors(entry))


def test_output_is_deterministic(tmp_path: Path) -> None:
    _dump(
        tmp_path,
        {
            f"R{i}": f'{{ z = {i}, a = {{ {i}, "s" }}, m = {{ q = {i} }} }}'
            for i in range(20)
        },
    )
    assert dbt.generate(tmp_path, (KIND,)) == dbt.generate(tmp_path, (KIND,))


def test_check_reports_drift(tmp_path: Path) -> None:
    g, out = tmp_path / "_G", tmp_path / "out"
    _dump(g, {"A": "{ a = 1 }"})
    files = dbt.generate(g, (KIND,))
    assert generated_drift(out, files, dbt.SUFFIX) == ["Test.generated.yaml"]
    dbt.write(files, out)
    assert generated_drift(out, files, dbt.SUFFIX) == []
    write(out / "Old.generated.yaml", "types: {}\n")
    assert generated_drift(out, files, dbt.SUFFIX) == ["Old.generated.yaml"]
    dbt.write(files, out)
    assert not (out / "Old.generated.yaml").exists()
    _dump(g, {"B": '{ a = "x" }'})
    assert generated_drift(out, dbt.generate(g, (KIND,)), dbt.SUFFIX) == [
        "Test.generated.yaml"
    ]


def test_missing_kind_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        dbt.generate(tmp_path, (KIND,))


def test_if_dumped_skips_without_a_dump_of_the_committed_version(
    tmp_path: Path,
) -> None:
    g, out = tmp_path / "_G", tmp_path / "out"
    base = ["--g-dir", str(g), "--out", str(out), "--check", "--if-dumped"]
    assert dbt.main(base) == 0  # no dump at all
    write(g / "__DCS_VERSION__.lua", "2.9.1.1")
    _dump(g, {"A": "{ a = 1 }"})
    files = dbt.generate(g, (KIND,))
    assert "# DCS version: 2.9.1.1" in files["Test.generated.yaml"]
    dbt.write(files, out)
    assert dbt.committed_version(out) == "2.9.1.1"
    write(g / "__DCS_VERSION__.lua", "2.9.2.1")
    assert dbt.main(base) == 0  # a dump of another version: skipped
    write(g / "__DCS_VERSION__.lua", "2.9.1.1")
    with pytest.raises(SystemExit):  # same version: checked (the real KINDS are absent)
        dbt.main(base)


def test_passing_check_is_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g, out = tmp_path / "_G", tmp_path / "out"
    monkeypatch.setattr(dbt, "CHECK_CACHE", tmp_path / "check")
    write(g / "__DCS_VERSION__.lua", "2.9.1.1")
    _dump(g, {"A": "{ a = 1 }"})
    real, calls = dbt.generate, []

    def generate(g_dir: Path) -> Any:
        calls.append(g_dir)
        return real(g_dir, (KIND,))

    monkeypatch.setattr(dbt, "generate", generate)
    dbt.write(real(g, (KIND,)), out)
    base = ["--g-dir", str(g), "--out", str(out), "--check"]
    assert dbt.main(base) == 0 and len(calls) == 1
    assert dbt.main(base) == 0 and len(calls) == 1
    write(out / "Test.generated.yaml", "types: {}\n")
    with pytest.raises(SystemExit):
        dbt.main(base)
    assert len(calls) == 2
