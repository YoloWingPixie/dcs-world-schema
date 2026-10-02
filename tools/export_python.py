#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from tools.datamine.common import load_json
from tools.spec_types import (
    Array,
    Literal,
    Map,
    Primitive,
    TypeNode,
    Union,
    api_spec,
    members,
    parse_type,
    strip_null,
)

TYPE_MAPPING = {
    "number": "float",
    "string": "str",
    "boolean": "bool",
    "table": "dict",
    "function": "Callable[..., Any]",
    "any": "Any",
    "nil": "None",
    "void": "None",
}

PYTHON_RESERVED_KEYWORDS = {
    "False",
    "None",
    "True",
    "and",
    "as",
    "assert",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
    "async",
    "await",
    "enum",
}

# Track processed types to avoid duplicates
processed_types: set[str] = set()


def sanitize_python_name(name: str) -> str:
    """Make a name safe for Python"""
    if not name:
        return "unnamed"

    name = name.replace(".", "_")

    name = name.replace("-", "_")

    name = name.replace(" ", "_")

    if name and name[0].isdigit():
        name = f"_{name}"

    name = name.replace("/", "_")
    name = name.replace("'", "")
    name = name.replace('"', "")
    name = name.replace("(", "")
    name = name.replace(")", "")
    name = name.replace("[", "")
    name = name.replace("]", "")

    if name in PYTHON_RESERVED_KEYWORDS:
        name = f"{name}_"

    return name


def map_type(type_str: str) -> str:
    """Map DCS schema type to Python type annotation"""
    if not type_str:
        return "Any"
    return render_type(parse_type(type_str))


def _first_literal(parts: tuple[TypeNode, ...]) -> TypeNode | None:
    return next((p for p in parts if isinstance(p, Literal)), None)


def _literals(parts: tuple[TypeNode, ...]) -> str:
    """One ``Literal[...]`` of the string literals among ``parts``."""
    values = [json.dumps(p.value) for p in parts if isinstance(p, Literal)]
    return f"Literal[{', '.join(values)}]"


def render_type(node: TypeNode) -> str:
    """The Python annotation of a typeRef node."""
    if isinstance(node, Union):
        # Python 3.10+ union type syntax; the string literals as one Literal.
        literals = _literals(node.members)
        return " | ".join(
            literals if isinstance(m, Literal) else render_type(m)
            for m in node.members
            if not isinstance(m, Literal) or m == _first_literal(node.members)
        )
    if isinstance(node, Array):
        return f"List[{render_type(node.item)}]"
    if isinstance(node, Map):
        return f"Dict[{render_type(node.key)}, {render_type(node.value)}]"
    if isinstance(node, Literal):
        return f"Literal[{json.dumps(node.value)}]"
    if isinstance(node, Primitive):
        return TYPE_MAPPING[node.name]
    # Reference to another type - keep original name
    return sanitize_python_name(node.name)


def record_field_type(type_str: str) -> tuple[str, bool]:
    """Python annotation of a record field's typeRef and whether it admits nil.

    ``nil`` members are dropped (the key becomes ``NotRequired`` instead).
    """
    return _field_type(parse_type(type_str or "any"))


def _field_type(node: TypeNode) -> tuple[str, bool]:
    non_null, nullable = strip_null(node)
    rendered: list[str] = []
    parts = members(non_null) if non_null is not None else ()
    for part in parts:
        if isinstance(part, Literal):
            if part != _first_literal(parts):
                continue
            py = _literals(parts)
        elif isinstance(part, Array):
            elem, elem_nullable = _field_type(part.item)
            py = f"List[{elem} | None]" if elem_nullable else f"List[{elem}]"
        elif isinstance(part, Map):
            key = part.key
            is_scalar = isinstance(key, Primitive) and key.name in ("string", "number")
            key_py = render_type(key) if is_scalar else "str"
            value_py, value_nullable = _field_type(part.value)
            if value_nullable:
                value_py = f"{value_py} | None"
            py = f"Dict[{key_py}, {value_py}]"
        else:
            py = render_type(part)
        if py not in rendered:
            rendered.append(py)
    if not rendered:
        return "None", True
    if "Any" in rendered:
        return "Any", nullable
    return " | ".join(rendered), nullable


def process_record(name: str, type_def: dict[str, Any]) -> str:
    """A ``kind: record`` type with fields as a ``TypedDict``.

    Keys in ``required`` are required; the rest (and keys whose typeRef admits
    ``nil``) are not. The module uses ``from __future__ import annotations``,
    so class-body ``NotRequired[...]`` would be invisible at runtime; totality
    is expressed with ``total=False`` instead (a required-keys base class when
    both kinds are present). Records whose keys are not all identifiers (e.g.
    ``from``) use the functional form, whose values are evaluated at runtime.
    """
    python_name = sanitize_python_name(name)
    desc = " ".join((type_def.get("description") or "").split())
    required = set(type_def.get("required") or [])
    fields: list[tuple[str, str, bool, str]] = []
    for field_name, field_def in type_def.get("fields", {}).items():
        py_type, nullable = record_field_type(field_def.get("type", "any"))
        optional = nullable or field_name not in required
        field_desc = " ".join((field_def.get("description") or "").split())
        fields.append((field_name, py_type, optional, field_desc))

    def body(members: list[tuple[str, str, bool, str]]) -> list[str]:
        out: list[str] = []
        for field_name, py_type, _, field_desc in members:
            if field_desc:
                out.append(f"    #: {field_desc}")
            out.append(f"    {field_name}: {py_type}")
        return out

    lines: list[str] = []
    identifiers = all(
        f.isidentifier() and f not in PYTHON_RESERVED_KEYWORDS for f, _, _, _ in fields
    )
    if identifiers:
        req = [f for f in fields if not f[2]]
        opt = [f for f in fields if f[2]]
        doc = [f"    {format_docstring(desc)}"] if desc else []
        if req and opt:
            base = f"_{python_name}_Required"
            lines.append(f"class {base}(TypedDict):")
            lines.append(f'    """Required keys of :class:`{python_name}`."""')
            lines.extend(body(req))
            lines.append("")
            lines.append(f"class {python_name}({base}, total=False):")
            lines.extend(doc)
            lines.extend(body(opt))
        elif opt:
            lines.append(f"class {python_name}(TypedDict, total=False):")
            lines.extend(doc)
            lines.extend(body(opt))
        else:
            lines.append(f"class {python_name}(TypedDict):")
            lines.extend(doc)
            lines.extend(body(req))
    else:
        if desc:
            lines.append(f"# {desc}")
        lines.append(f"{python_name} = TypedDict(")
        lines.append(f"    {json.dumps(python_name)},")
        lines.append("    {")
        for field_name, py_type, optional, field_desc in fields:
            value = json.dumps(py_type)
            if optional:
                value = f"NotRequired[{value}]"
            if field_desc:
                lines.append(f"        #: {field_desc}")
            lines.append(f"        {json.dumps(field_name)}: {value},")
        lines.append("    },")
        lines.append(")")
    lines.append("")
    return "\n".join(lines)


def process_union(name: str, type_def: dict[str, Any]) -> str:
    """A ``kind: union`` type as a ``Union`` alias; members are quoted (forward
    references), as they may be defined further down the module."""
    members = [json.dumps(map_type(t)) for t in type_def.get("anyOf") or []]
    desc = " ".join((type_def.get("description") or "").split())
    lines = [f"# {desc}"] if desc else []
    value = f"Union[{', '.join(members)}]" if members else "Any"
    lines.append(f"{sanitize_python_name(name)} = {value}")
    lines.append("")
    return "\n".join(lines)


def format_docstring(desc: str) -> str:
    """Format a description for a Python docstring"""
    if not desc:
        return ""

    # Remove any existing explicit triple quotes to avoid breaking docstring format
    desc = desc.replace('"""', "'''")

    # Wrap multiline docstrings
    if "\n" in desc:
        return f'"""{desc}"""'

    return f'"""{desc}"""'


def _member_name(key: str, taken: set[str]) -> str:
    """An enum member name for ``key``: an identifier, no Enum ``_sunder_``
    name, unique among ``taken``."""
    name = sanitize_python_name(key)
    if not name.isidentifier():
        name = re.sub(r"\W", "_", name)
    if name.startswith("_") and name.endswith("_"):
        name = f"N{name}"
    base, n = name, 2
    while name in taken:
        name, n = f"{base}_{n}", n + 1
    taken.add(name)
    return name


def process_enum(name: str, enum_def: dict[str, Any]) -> str:
    """Process an enum into Python Enum class"""
    values = enum_def.get("values", [])
    desc = enum_def.get("description", "")

    python_name = sanitize_python_name(name)

    lines = []

    lines.append(f"class {python_name}(str, Enum):")
    if desc:
        lines.append(f"    {format_docstring(desc)}")

    taken: set[str] = set()
    if isinstance(values, list):
        for val in values:
            if isinstance(val, str):
                safe_val = _member_name(val, taken)
                lines.append(f"    {safe_val} = {json.dumps(val)}")
    elif isinstance(values, dict):
        for key, value in values.items():
            if isinstance(value, str):
                formatted_value = json.dumps(value)
            elif isinstance(value, (int, float)):
                formatted_value = str(value)
            else:
                formatted_value = json.dumps(key)  # Default fallback

            safe_key = _member_name(key, taken)
            lines.append(f"    {safe_key} = {formatted_value}")
    elif isinstance(values, str):
        safe_val = sanitize_python_name(values)
        lines.append(f'    {safe_val} = "{values}"')

    # Ensure there's at least one member if the enum is empty
    if not values:
        lines.append('    UNDEFINED = "UNDEFINED"')

    lines.append("")  # Empty line after class
    return "\n".join(lines)


def process_type_definition(name: str, type_def: dict[str, Any]) -> str:
    """Process a type into Python class definition"""
    if name in processed_types:
        return ""

    processed_types.add(name)

    kind = type_def.get("kind", "")

    if kind == "enum":
        return process_enum(name, type_def)

    if kind == "record" and type_def.get("fields"):
        return process_record(name, type_def)

    if kind == "union":
        return process_union(name, type_def)

    desc = type_def.get("description", "")
    inherits = type_def.get("inherits", "")

    python_name = sanitize_python_name(name)

    lines = []

    if inherits:
        parent_class = sanitize_python_name(inherits)
        lines.append(f"class {python_name}({parent_class}):")
    else:
        lines.append(f"class {python_name}:")

    if desc:
        lines.append(f"    {format_docstring(desc)}")

    properties = type_def.get("properties", {})
    static_props = type_def.get("static", {})

    # Combine regular and static properties for Python
    all_props = {}
    all_props.update(properties)
    all_props.update(static_props)

    if all_props:
        lines.append("    def __init__(self) -> None:")

        for prop_name, prop_def in all_props.items():
            prop_type = prop_def.get("type", "any")
            prop_desc = prop_def.get("description", "")
            prop_notes = prop_def.get("notes", "")

            safe_prop_name = sanitize_python_name(prop_name)

            combined_desc = prop_desc
            if prop_notes:
                if combined_desc:
                    combined_desc = f"{combined_desc}\n\n{prop_notes}"
                else:
                    combined_desc = prop_notes

            # A trailing comment must stay on one line
            combined_desc = " ".join(combined_desc.split())

            if isinstance(prop_type, list):
                types = [map_type(t) for t in prop_type if isinstance(t, str)]
                type_str = " | ".join(types) if types else "Any"
                lines.append(
                    f"        self.{safe_prop_name}: {type_str} = None  # {combined_desc}"
                    if combined_desc
                    else f"        self.{safe_prop_name}: {type_str} = None"
                )
            else:
                lines.append(
                    f"        self.{safe_prop_name}: {map_type(prop_type)} = None  # {combined_desc}"
                    if combined_desc
                    else f"        self.{safe_prop_name}: {map_type(prop_type)} = None"
                )
    else:
        lines.append("    pass")

    instance_methods = type_def.get("instance", {})
    for method_name, method_def in instance_methods.items():
        method_str = process_method(method_name, method_def)
        lines.extend(["    " + line for line in method_str.split("\n") if line])

    lines.append("")  # Empty line after class
    return "\n".join(lines)


def process_method(method_name: str, method_def: dict[str, Any]) -> str:
    """Process a method into Python method definition"""
    params = method_def.get("params", [])
    returns = method_def.get("returns", "void")
    desc = method_def.get("description", "")
    notes = method_def.get("notes", "")

    combined_desc = desc
    if notes:
        combined_desc = f"{combined_desc}\n\n{notes}" if combined_desc else notes

    lines = []

    safe_method_name = sanitize_python_name(method_name)

    param_list = ["self"]
    for param in params:
        param_name = sanitize_python_name(param.get("name", f"param{len(param_list)}"))
        param_type = param.get("type", "any")

        if isinstance(param_type, list):
            types = [map_type(t) for t in param_type if isinstance(t, str)]
            type_str = " | ".join(types) if types else "Any"
            param_list.append(f"{param_name}: {type_str}")
        else:
            param_list.append(f"{param_name}: {map_type(param_type)}")

    if returns and returns != "void":
        if isinstance(returns, list):
            return_types = [
                map_type(rt) for rt in returns if isinstance(rt, str) and rt != "void"
            ]
            return_type = " | ".join(return_types) if return_types else "None"
        else:
            return_type = map_type(returns)
    else:
        return_type = "None"

    lines.append(f"def {safe_method_name}({', '.join(param_list)}) -> {return_type}:")

    if combined_desc:
        docstring = [combined_desc]

        param_docs = []
        for param in params:
            param_name = sanitize_python_name(param.get("name", "param"))
            param_desc = param.get("description", "")
            if param_desc:
                param_docs.append("    Args:")
                param_docs.append(f"        {param_name}: {param_desc}")

        if param_docs:
            docstring.extend(param_docs)

        if returns and returns != "void":
            docstring.append("    Returns:")
            docstring.append(f"        {return_type}: Return value")

        lines.append(f"    {format_docstring('\\n'.join(docstring))}")

    lines.append("    pass")

    return "\n".join(lines)


def process_global(name: str, global_def: dict[str, Any]) -> str:
    """Process a global namespace into Python class or module"""
    desc = global_def.get("description", "")
    notes = global_def.get("notes", "")

    combined_desc = desc
    if notes:
        combined_desc = f"{combined_desc}\n\n{notes}" if combined_desc else notes

    python_name = sanitize_python_name(name)
    props_with_notes: list[dict[str, Any]] = []
    lines = []

    lines.append(f"class {python_name}:")

    if combined_desc:
        lines.append(f"    {format_docstring(combined_desc)}")

    properties = global_def.get("properties", {})
    static_props = global_def.get("static", {})

    # Combine regular and static properties for Python
    all_props = {}
    all_props.update(properties)
    all_props.update(static_props)

    if all_props:
        lines.append("    def __init__(self) -> None:")

        for i, (prop_name, prop_def) in enumerate(all_props.items()):
            prop_type = prop_def.get("type", "any")
            prop_desc = prop_def.get("description", "")
            prop_notes = prop_def.get("notes", "")

            safe_prop_name = sanitize_python_name(prop_name)

            combined_prop_desc = prop_desc
            if prop_notes:
                if combined_prop_desc:
                    combined_prop_desc = f"{combined_prop_desc}\n\n{prop_notes}"
                else:
                    combined_prop_desc = prop_notes

            # Keep track of properties with notes for later
            if prop_notes:
                props_with_notes.append(
                    {"name": safe_prop_name, "index": i, "notes": prop_notes}
                )

            # A trailing comment must stay on one line
            combined_prop_desc = " ".join(combined_prop_desc.split())

            if isinstance(prop_type, list):
                types = [map_type(t) for t in prop_type if isinstance(t, str)]
                type_str = " | ".join(types) if types else "Any"
                lines.append(
                    f"        self.{safe_prop_name}: {type_str} = None  # {combined_prop_desc}"
                    if combined_prop_desc
                    else f"        self.{safe_prop_name}: {type_str} = None"
                )
            else:
                lines.append(
                    f"        self.{safe_prop_name}: {map_type(prop_type)} = None  # {combined_prop_desc}"
                    if combined_prop_desc
                    else f"        self.{safe_prop_name}: {map_type(prop_type)} = None"
                )
    else:
        lines.append("    pass")

    instance_methods = global_def.get("instance", {})
    for method_name, method_def in instance_methods.items():
        method_str = process_method(method_name, method_def)
        lines.extend(["    " + line for line in method_str.split("\n") if line])

    # Add instantiated variable for singleton access
    lines.append("")
    lines.append(f"{name.lower()} = {python_name}()")
    lines.append("")

    return "\n".join(lines)


def _indent(line: str) -> str:
    """The leading whitespace of ``line``."""
    m = re.match(r"\s*", line)
    return m.group(0) if m else ""


def export_to_python(schema: dict[str, Any], output_path: str) -> None:
    """Export schema to Python type hints"""
    schema = api_spec(schema)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    processed_types.clear()

    lines = [
        "#!/usr/bin/env python3",
        "# DCS World API Python Type Definitions",
        "# Generated from DCS World Schema",
        "# DO NOT MODIFY - AUTO-GENERATED FILE",
        "",
        "from __future__ import annotations",
        "",
        "from enum import Enum",
        "from typing import Any, Dict, List, Tuple, Union, Optional, Callable",
        "from typing import Literal, NotRequired, TypedDict",
        "",
        "# Type Definitions",
    ]

    # Dotted (namespace) types go after the globals
    if "types" in schema:
        for type_name, type_def in sorted(schema["types"].items()):
            if "." in type_name:
                continue

            type_definition = process_type_definition(type_name, type_def)
            if type_definition:
                lines.append(type_definition)

    if "globals" in schema:
        lines.append("# Global Namespaces")
        for global_name, global_def in sorted(schema["globals"].items()):
            lines.append(process_global(global_name, global_def))

    if "types" in schema:
        lines.append("# Namespace Types")
        for type_name, type_def in sorted(schema["types"].items()):
            if "." in type_name and type_name not in processed_types:
                lines.append(process_type_definition(type_name, type_def))

    # Comment out prose lines that are not valid Python
    processed_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            processed_lines.append(line)
            i += 1
            continue

        # Move a "Note:" in a property's trailing comment onto its own line.
        # Only split single-line entries: a multi-line entry (a whole class)
        # would otherwise be truncated to the matched line.
        match_note = "\n" not in line and re.search(
            r"(self\.[a-zA-Z0-9_]+:.+#.+)(Note:.*)", line
        )
        if match_note:
            code_part = match_note.group(1).rstrip()
            note_part = match_note.group(2).strip()

            indent = _indent(line)
            processed_lines.append(indent + code_part)

            processed_lines.append(f"{indent}# {note_part}")

            i += 1
            continue

        # Bare prose (a note, or text outside any statement): comment it out.
        if (
            stripped.startswith("Note:")
            or re.match(
                r"^[A-Z][a-z]+:", stripped
            )  # Any capitalized word followed by colon
            or (
                not line.startswith(" ")
                and not line.startswith("\t")
                and not stripped.startswith("class ")
                and not stripped.startswith("def ")
                and not stripped.startswith("#")
                and not stripped.startswith("from ")
                and not stripped.startswith("import ")
                and "=" not in stripped
            )
        ):
            note_lines = [stripped]
            next_i = i + 1

            # Continuation lines of the note
            while next_i < len(lines):
                next_line = lines[next_i].strip()
                if (
                    not next_line
                    or next_line.startswith(
                        ("class ", "def ", "# ", "from ", "import ")
                    )
                    or (
                        "=" in next_line
                        and " = " in next_line
                        and not next_line.startswith(" ")
                    )
                ):
                    break

                note_lines.append(next_line)
                next_i += 1

            indent = _indent(line)

            complete_note = " ".join(note_lines)

            # Over 75 columns: one line per sentence, else wrap at spaces
            if len(complete_note) > 75:
                sentences = []
                parts = re.split(r"([.!?] )", complete_note)
                for j in range(0, len(parts) - 1, 2):
                    if j + 1 < len(parts):
                        sentences.append(parts[j] + parts[j + 1])
                if len(parts) % 2 == 1:
                    sentences.append(parts[-1])

                if len(sentences) <= 1:
                    words = complete_note.split(" ")
                    current_line = words[0]
                    for word in words[1:]:
                        if len(current_line) + len(word) + 1 <= 75:
                            current_line += " " + word
                        else:
                            processed_lines.append(f"{indent}# {current_line}")
                            current_line = word
                    if current_line:
                        processed_lines.append(f"{indent}# {current_line}")
                else:
                    for sentence in sentences:
                        processed_lines.append(f"{indent}# {sentence}")
            else:
                processed_lines.append(f"{indent}# {complete_note}")

            i = next_i
        else:
            processed_lines.append(line)
            i += 1

    # Final pass to catch any free-standing "Note:" lines
    final_lines = []
    for line in processed_lines:
        stripped = line.strip()
        if stripped.startswith("Note:") or (
            not line.startswith(" ")
            and not line.startswith("#")
            and not line.startswith("class ")
            and not line.startswith("def ")
            and not stripped.startswith("from ")
            and "=" not in stripped
            and len(stripped) > 0
        ):
            final_lines.append(f"# {stripped}")
        else:
            final_lines.append(line)

    with Path(output_path).open("w", encoding="utf-8") as f:
        f.write("\n".join(final_lines))

    # Comment out remaining prose that would be a syntax error
    with Path(output_path).open(encoding="utf-8") as f:
        content = f.read()

    pattern = r"^(\s*)Note:"
    fixed_content = re.sub(pattern, r"\1# Note:", content, flags=re.MULTILINE)

    # Sentences starting with these words
    problem_words = ["When", "The", "This", "If", "Use", "For", "In"]
    for word in problem_words:
        pattern = rf"^(\s*)({word}\s.*)"
        fixed_content = re.sub(pattern, r"\1# \2", fixed_content, flags=re.MULTILINE)

    # Backticks are a syntax error
    fixed_content = re.sub(r"`([^`]+)`", r"'\1'", fixed_content)

    with Path(output_path).open("w", encoding="utf-8") as f:
        f.write(fixed_content)

    print(f"Python type definitions exported to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export DCS schema to Python type hints"
    )
    parser.add_argument("schema", help="Path to the DCS schema JSON file")
    parser.add_argument(
        "--output",
        "-o",
        default="dist/dcs_world_api.py",
        help="Output Python definition file (default: dist/dcs_world_api.py)",
    )

    args = parser.parse_args()

    try:
        schema = load_json(Path(args.schema))
        export_to_python(schema, args.output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
