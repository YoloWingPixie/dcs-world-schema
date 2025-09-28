#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Set


# Python type mapping
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

# Python reserved keywords to avoid
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
processed_types: Set[str] = set()


def load_schema(path: str) -> Dict[str, Any]:
    """Load the schema from a JSON file"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_python_name(name: str) -> str:
    """Make a name safe for Python"""
    if not name:
        return "unnamed"

    # Replace dots with underscores for Python module imports
    name = name.replace(".", "_")

    # Replace hyphens with underscores
    name = name.replace("-", "_")

    # Replace spaces with underscores
    name = name.replace(" ", "_")

    # If starts with a number, prefix with underscore
    if name and name[0].isdigit():
        name = f"_{name}"

    # Replace other invalid characters
    name = name.replace("/", "_")
    name = name.replace("'", "")
    name = name.replace('"', "")
    name = name.replace("(", "")
    name = name.replace(")", "")
    name = name.replace("[", "")
    name = name.replace("]", "")

    # Handle reserved keywords
    if name in PYTHON_RESERVED_KEYWORDS:
        name = f"{name}_"

    return name


def map_type(type_str: str) -> str:
    """Map DCS schema type to Python type annotation"""
    if not type_str:
        return "Any"

    # Handle union types
    if "|" in type_str:
        types = [map_type(t.strip()) for t in type_str.split("|")]
        return " | ".join(types)  # Python 3.10+ union type syntax

    # Handle array types
    if type_str.endswith("[]"):
        base_type = type_str[:-2].strip()
        return f"List[{map_type(base_type)}]"

    # Handle map types
    if type_str.startswith("map<") and type_str.endswith(">"):
        # Extract key and value types
        inner = type_str[4:-1].strip()
        parts = inner.split(",")
        if len(parts) == 2:
            key_type, value_type = parts
            return f"Dict[{map_type(key_type.strip())}, {map_type(value_type.strip())}]"
        return f"Dict[str, {map_type(inner)}]"

    # Handle primitive types
    if type_str in TYPE_MAPPING:
        return TYPE_MAPPING[type_str]

    # Reference to another type - keep original name
    return sanitize_python_name(type_str)


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


def process_enum(name: str, enum_def: Dict[str, Any]) -> str:
    """Process an enum into Python Enum class"""
    values = enum_def.get("values", [])
    desc = enum_def.get("description", "")

    python_name = sanitize_python_name(name)

    lines = []

    # Add class definition with docstring
    lines.append(f"class {python_name}(str, Enum):")
    if desc:
        lines.append(f"    {format_docstring(desc)}")

    # Handle different formats of enum values
    if isinstance(values, list):
        # List format
        for i, val in enumerate(values):
            if isinstance(val, str):
                # Convert to valid Python identifier
                safe_val = sanitize_python_name(val)
                lines.append(f'    {safe_val} = "{val}"')
    elif isinstance(values, dict):
        # Object format (key-value pairs)
        for key, value in values.items():
            # Format value based on its type
            if isinstance(value, str):
                formatted_value = f'"{value}"'
            elif isinstance(value, (int, float)):
                formatted_value = str(value)
            else:
                formatted_value = f'"{key}"'  # Default fallback

            # Convert to valid Python identifier
            safe_key = sanitize_python_name(key)
            lines.append(f"    {safe_key} = {formatted_value}")
    elif isinstance(values, str):
        # Single string value
        safe_val = sanitize_python_name(values)
        lines.append(f'    {safe_val} = "{values}"')

    # Ensure there's at least one member if the enum is empty
    if not values:
        lines.append('    UNDEFINED = "UNDEFINED"')

    lines.append("")  # Empty line after class
    return "\n".join(lines)


def process_type_definition(name: str, type_def: Dict[str, Any]) -> str:
    """Process a type into Python class definition"""
    if name in processed_types:
        return ""

    processed_types.add(name)

    # Different handling based on type
    kind = type_def.get("kind", "")

    if kind == "enum":
        return process_enum(name, type_def)

    # For regular types, create a class
    desc = type_def.get("description", "")
    inherits = type_def.get("inherits", "")

    python_name = sanitize_python_name(name)

    lines = []

    # Add class definition with inheritance if specified
    if inherits:
        parent_class = sanitize_python_name(inherits)
        lines.append(f"class {python_name}({parent_class}):")
    else:
        lines.append(f"class {python_name}:")

    # Add docstring if there's a description
    if desc:
        lines.append(f"    {format_docstring(desc)}")

    # Properties
    properties = type_def.get("properties", {})
    static_props = type_def.get("static", {})

    # Combine regular and static properties for Python
    all_props = {}
    all_props.update(properties)
    all_props.update(static_props)

    if all_props:
        # Add constructor to initialize properties
        lines.append("    def __init__(self) -> None:")

        for prop_name, prop_def in all_props.items():
            prop_type = prop_def.get("type", "any")
            prop_desc = prop_def.get("description", "")
            prop_notes = prop_def.get("notes", "")

            # Convert property name to Python safe name
            safe_prop_name = sanitize_python_name(prop_name)

            # Combine description and notes if available
            combined_desc = prop_desc
            if prop_notes:
                if combined_desc:
                    combined_desc = f"{combined_desc}\n\n{prop_notes}"
                else:
                    combined_desc = prop_notes

            # Add property initialization with type comment
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
        # Add a pass if no properties
        lines.append("    pass")

    # Add methods
    instance_methods = type_def.get("instance", {})
    for method_name, method_def in instance_methods.items():
        method_str = process_method(method_name, method_def)
        lines.extend(["    " + line for line in method_str.split("\n") if line])

    lines.append("")  # Empty line after class
    return "\n".join(lines)


def process_method(method_name: str, method_def: Dict[str, Any]) -> str:
    """Process a method into Python method definition"""
    params = method_def.get("params", [])
    returns = method_def.get("returns", "void")
    desc = method_def.get("description", "")
    notes = method_def.get("notes", "")

    # Combine description and notes
    combined_desc = desc
    if notes:
        if combined_desc:
            combined_desc = f"{combined_desc}\n\n{notes}"
        else:
            combined_desc = notes

    lines = []

    # Convert method name to Python safe name
    safe_method_name = sanitize_python_name(method_name)

    # Build parameter list
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

    # Determine return type
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

    # Create the method signature
    lines.append(f"def {safe_method_name}({', '.join(param_list)}) -> {return_type}:")

    # Add docstring if there's a description
    if combined_desc:
        docstring = [combined_desc]

        # Add parameter descriptions in the docstring
        param_docs = []
        for param in params:
            param_name = sanitize_python_name(param.get("name", "param"))
            param_desc = param.get("description", "")
            if param_desc:
                param_docs.append("    Args:")
                param_docs.append(f"        {param_name}: {param_desc}")

        if param_docs:
            docstring.extend(param_docs)

        # Add return description
        if returns and returns != "void":
            docstring.append("    Returns:")
            docstring.append(f"        {return_type}: Return value")

        lines.append(f"    {format_docstring('\\n'.join(docstring))}")

    # Add method body with pass
    lines.append("    pass")

    return "\n".join(lines)


def process_global(name: str, global_def: Dict[str, Any]) -> str:
    """Process a global namespace into Python class or module"""
    desc = global_def.get("description", "")
    notes = global_def.get("notes", "")

    # Combine description and notes
    combined_desc = desc
    if notes:
        if combined_desc:
            combined_desc = f"{combined_desc}\n\n{notes}"
        else:
            combined_desc = notes

    python_name = sanitize_python_name(name)
    props_with_notes: List[Dict[str, Any]] = []
    lines = []

    # Add class definition
    lines.append(f"class {python_name}:")

    # Add docstring if there's a description
    if combined_desc:
        lines.append(f"    {format_docstring(combined_desc)}")

    # Properties
    properties = global_def.get("properties", {})
    static_props = global_def.get("static", {})

    # Combine regular and static properties for Python
    all_props = {}
    all_props.update(properties)
    all_props.update(static_props)

    if all_props:
        # Add constructor to initialize properties
        lines.append("    def __init__(self) -> None:")

        last_prop_index = 0

        # Iterate through properties and track their notes
        for i, (prop_name, prop_def) in enumerate(all_props.items()):
            prop_type = prop_def.get("type", "any")
            prop_desc = prop_def.get("description", "")
            prop_notes = prop_def.get("notes", "")

            # Convert property name to Python safe name
            safe_prop_name = sanitize_python_name(prop_name)

            # Combine description and notes if available
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
                last_prop_index = i

            # Add property initialization with type comment
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
        # Add a pass if no properties
        lines.append("    pass")

    # Add methods
    instance_methods = global_def.get("instance", {})
    for method_name, method_def in instance_methods.items():
        method_str = process_method(method_name, method_def)
        lines.extend(["    " + line for line in method_str.split("\n") if line])

    # Add instantiated variable for singleton access
    lines.append("")
    lines.append(f"{name.lower()} = {python_name}()")
    lines.append("")

    return "\n".join(lines)


def export_to_python(schema: Dict[str, Any], output_path: str) -> None:
    """Export schema to Python type hints"""
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    lines = [
        "#!/usr/bin/env python3",
        "# DCS World API Python Type Definitions",
        "# Generated from DCS World Schema",
        "# DO NOT MODIFY - AUTO-GENERATED FILE",
        "",
        "from enum import Enum",
        "from typing import Any, Dict, List, Tuple, Union, Optional, Callable",
        "",
        "# Type Definitions",
    ]

    # Process standalone types first
    if "types" in schema:
        for type_name, type_def in sorted(schema["types"].items()):
            # Skip namespace types for now
            if "." in type_name:
                continue

            type_definition = process_type_definition(type_name, type_def)
            if type_definition:
                lines.append(type_definition)

    # Process globals
    if "globals" in schema:
        lines.append("# Global Namespaces")
        for global_name, global_def in sorted(schema["globals"].items()):
            lines.append(process_global(global_name, global_def))

    # Process namespace types
    if "types" in schema:
        lines.append("# Namespace Types")
        for type_name, type_def in sorted(schema["types"].items()):
            if "." in type_name and type_name not in processed_types:
                lines.append(process_type_definition(type_name, type_def))

    # Process the lines to fix any invalid Python syntax
    processed_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            processed_lines.append(line)
            i += 1
            continue

        # Check if this line is a method/property docstring with a comment inside it
        match_note = re.search(r"(self\.[a-zA-Z0-9_]+:.+#.+)(Note:.*)", line)
        if match_note:
            # Split the line at the Note: marker
            code_part = match_note.group(1).rstrip()
            note_part = match_note.group(2).strip()

            # Add the code part first
            processed_lines.append(code_part)

            # Then add the note as a separate comment line with proper indentation
            indent = re.match(r"^(\s*)", line).group(1)
            processed_lines.append(f"{indent}# {note_part}")

            i += 1
            continue

        # Handle standalone notes that aren't properly commented
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
            # Collect multi-line note content
            note_lines = [stripped]
            next_i = i + 1

            # Look ahead for continuation of the note
            while next_i < len(lines):
                next_line = lines[next_i].strip()
                if (
                    not next_line
                    or next_line.startswith("class ")
                    or next_line.startswith("def ")
                    or next_line.startswith("# ")
                    or next_line.startswith("from ")
                    or next_line.startswith("import ")
                    or "=" in next_line
                    and " = " in next_line
                    and not next_line.startswith(" ")
                ):
                    break

                # Collect this line as part of the note
                note_lines.append(next_line)
                next_i += 1

            # Process all lines of the note and add as comments
            # Get the indentation of the current line
            indent = re.match(r"^(\s*)", line).group(1)

            # Join the note lines and create a properly formatted comment
            complete_note = " ".join(note_lines)

            # Break long comments into multiple lines
            if len(complete_note) > 75:
                # First try to split on natural sentence boundaries
                sentences = []
                parts = re.split(r"([.!?] )", complete_note)
                for j in range(0, len(parts) - 1, 2):
                    if j + 1 < len(parts):
                        sentences.append(parts[j] + parts[j + 1])
                if len(parts) % 2 == 1:
                    sentences.append(parts[-1])

                # If there are no sentence breaks, split on spaces
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
                    # Use the natural sentence breaks
                    for sentence in sentences:
                        processed_lines.append(f"{indent}# {sentence}")
            else:
                # Short enough for a single line
                processed_lines.append(f"{indent}# {complete_note}")

            # Skip processed lines
            i = next_i
        else:
            # Regular line, just add it
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
            # This is still a standalone note that wasn't properly caught
            final_lines.append(f"# {stripped}")
        else:
            final_lines.append(line)

    # Write to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(final_lines))

    # Additional post-processing to catch any remaining problematic lines
    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Use regex to find and fix any standalone Note: lines
    # This handles both 'Note:' at the beginning of a line and as its own statement
    pattern = r"^(\s*)Note:"
    fixed_content = re.sub(pattern, r"\1# Note:", content, flags=re.MULTILINE)

    # Also look for any other unattached capitalized words that would be syntax errors
    problem_words = ["When", "The", "This", "If", "Use", "For", "In"]
    for word in problem_words:
        pattern = rf"^(\s*)({word}\s.*)"
        fixed_content = re.sub(pattern, r"\1# \2", fixed_content, flags=re.MULTILINE)

    # One more check: look for standalone backticks which cause syntax errors
    fixed_content = re.sub(r"`([^`]+)`", r"'\1'", fixed_content)

    # Write the fixed content back to the file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(fixed_content)

    print(f"Python type definitions exported to {output_path}")


def main():
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
        schema = load_schema(args.schema)
        export_to_python(schema, args.output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
