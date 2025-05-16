#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Set, Union
import datetime

# LUA primitive type mapping
TYPE_MAPPING = {
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "table": "table",
    "function": "fun(...)", # EmmyLua convention for generic function
    "any": "any",
    "nil": "nil",
    "void": "nil",
}

# Track processed types to avoid re-defining ---@class/---@alias/---@enum annotations
processed_types: Set[str] = set()
# Track globals/namespaces for which Lua tables have been initialized
initialized_lua_tables: Set[str] = set()


def load_schema(path: str) -> Dict[str, Any]:
    """Load the schema from a JSON file"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_lua_name(name: str) -> str:
    """Make a name safe for Lua, e.g. for parameters or local variables."""
    name = name.replace(".", "_")
    name = name.replace("/", "_or_")
    if " enum" in name: # Specific to a naming convention in the input schema
        name = name.replace(" enum", "")
    if " " in name:
        name = name.replace(" ", "_")

    lua_keywords = {"end", "function", "if", "else", "then", "local", "and", "or", "not", "type", "repeat", "while", "for", "do", "return", "break", "goto", "in", "nil", "true", "false"}
    if name in lua_keywords:
        return f"_{name}"
    return name


def map_type(type_str: Union[str, List[str]]) -> str:
    """Map DCS schema type to Lua type annotation"""
    if isinstance(type_str, list): # For union types represented as a list
        return "|".join(sorted(list(set(map_type(t) for t in type_str))))

    if not type_str:
        return "any"
    if "|" in type_str:
        types = [map_type(t.strip()) for t in type_str.split("|")]
        return "|".join(sorted(list(set(types))))
    if type_str.endswith("[]"):
        base_type = type_str[:-2].strip()
        return f"{map_type(base_type)}[]"
    if type_str.startswith("map<") and type_str.endswith(">"): # e.g. map<string, number>
        inner_content = type_str[4:-1].strip()
        parts = inner_content.split(",", 1)
        if len(parts) == 2:
            key_type = map_type(parts[0].strip())
            value_type = map_type(parts[1].strip())
            return f"table<{key_type}, {value_type}>"
        else: # Fallback if parsing fails, e.g. map<MyType>
            return f"table<any, {map_type(inner_content)}>"
    if type_str in TYPE_MAPPING:
        return TYPE_MAPPING[type_str]
    return type_str # Assume it's a custom type


def format_description(desc: str, indent: str = "") -> str:
    """Format description as a block of EmmyLua comments."""
    if not desc:
        return ""
    lines = desc.strip().split("\n")
    if not lines:
        return ""
    block_result = ""
    for line_content in lines:
        block_result += f"{indent}--- {line_content.strip()}\n"
    return block_result

def format_multiline_annotation_desc(description: str) -> str:
    """Formats a multi-line description to be appended to an EmmyLua annotation line."""
    if not description:
        return ""
    lines = description.strip().split('\n')
    if not lines:
        return ""
    formatted = " " + lines[0].strip()
    if len(lines) > 1:
        for i in range(1, len(lines)):
            stripped_line = lines[i].strip()
            if stripped_line:
                formatted += f"\n--- {stripped_line}"
    return formatted


def process_param_for_annotation(param: Dict[str, Any]) -> str:
    name = param.get("name", "param")
    type_str = param.get("type", "any")
    desc = param.get("description", "")
    optional = param.get("optional", False)
    lua_name = sanitize_lua_name(name)
    if optional:
        lua_name += "?"
    lua_type = map_type(type_str)
    annotation = f"---@param {lua_name} {lua_type}"
    if desc:
        annotation += format_multiline_annotation_desc(desc)
    return annotation


def generate_fun_signature_for_field(func_def: Dict[str, Any]) -> str:
    params_list = func_def.get("params", [])
    returns_list = func_def.get("returns", [])
    param_signatures = []
    for p_idx, param_item in enumerate(params_list):
        p_name = sanitize_lua_name(param_item.get("name", f"p{p_idx+1}"))
        p_type = map_type(param_item.get("type", "any"))
        if param_item.get("optional", False):
            p_name += "?"
        param_signatures.append(f"{p_name}:{p_type}")
    actual_returns_for_fun_sig = []
    if isinstance(returns_list, str):
        mapped_ret = map_type(returns_list)
        if mapped_ret != "nil":
            actual_returns_for_fun_sig.append(mapped_ret)
    elif isinstance(returns_list, list):
        for ret_item in returns_list:
            ret_type_str_val = ""
            if isinstance(ret_item, str): ret_type_str_val = map_type(ret_item)
            elif isinstance(ret_item, dict): ret_type_str_val = map_type(ret_item.get("type", "any"))
            if ret_type_str_val and ret_type_str_val != "nil": actual_returns_for_fun_sig.append(ret_type_str_val)
            elif ret_type_str_val == "nil": actual_returns_for_fun_sig.append("nil")
    if not actual_returns_for_fun_sig: return_signature_for_fun = "void"
    elif len(actual_returns_for_fun_sig) == 1: return_signature_for_fun = actual_returns_for_fun_sig[0]
    else: return_signature_for_fun = f"({', '.join(actual_returns_for_fun_sig)})"
    return f"fun({', '.join(param_signatures)}):{return_signature_for_fun}"


def process_function_common(class_name_or_nil: str, func_name: str, func_def: Dict[str, Any], is_static: bool) -> str:
    params_list = func_def.get("params", [])
    returns_list = func_def.get("returns", [])
    desc = func_def.get("description", "")
    added_version = func_def.get("addedVersion", "")
    examples = func_def.get("examples", [])
    result = format_description(desc)
    if added_version: result += f"---@version {added_version}\n"
    for param_def in params_list:
        result += process_param_for_annotation(param_def) + "\n"
    actual_returns_for_annotation = []
    if isinstance(returns_list, str):
        mapped_ret = map_type(returns_list)
        if mapped_ret != "nil": actual_returns_for_annotation.append(mapped_ret)
    elif isinstance(returns_list, list):
        for ret_item in returns_list:
            ret_type_str_val = ""
            if isinstance(ret_item, str): ret_type_str_val = map_type(ret_item)
            elif isinstance(ret_item, dict): ret_type_str_val = map_type(ret_item.get("type", "any"))
            if ret_type_str_val: actual_returns_for_annotation.append(ret_type_str_val)
    if not (len(actual_returns_for_annotation) == 1 and actual_returns_for_annotation[0] == "nil"):
        for ret_type_str_val in actual_returns_for_annotation:
            result += f"---@return {ret_type_str_val}\n"
    if examples:
        result += "--- ### Examples\n"
        for example in examples:
            example_desc = example.get("description", "")
            example_code = example.get("code", "")
            if example_desc: result += format_description(example_desc, "--- ")
            if example_code:
                result += "--- ```lua\n"
                for line in example_code.split('\n'): result += f"--- {line}\n"
                result += "--- ```\n"
    sanitized_params_for_sig = [sanitize_lua_name(p.get("name", f"arg{i+1}")) for i, p in enumerate(params_list)]
    lua_func_name = sanitize_lua_name(func_name)
    if lua_func_name != func_name and (not hasattr(func_name, 'isidentifier') or not func_name.isidentifier()):
        lua_func_name = f'["{func_name}"]'
    separator = "." if is_static else ":"
    if class_name_or_nil:
        result += f"function {class_name_or_nil}{separator}{lua_func_name}({', '.join(sanitized_params_for_sig)}) end\n\n"
    else:
        result += f"function {lua_func_name}({', '.join(sanitized_params_for_sig)}) end\n\n"
    return result

def process_method(class_name: str, method_name: str, method_def: Dict[str, Any]) -> str:
    return process_function_common(class_name, method_name, method_def, is_static=False)

def process_static_function(class_name: str, func_name: str, func_def: Dict[str, Any]) -> str:
    return process_function_common(class_name, func_name, func_def, is_static=True)


def ensure_lua_table_initialized(name: str, existing_code_parts: List[str]) -> None:
    parts = name.split('.')
    current_path = ""
    for i, part in enumerate(parts):
        if current_path: current_path += "." + part
        else: current_path = part
        if current_path not in initialized_lua_tables:
            if i == 0 and '.' not in current_path:
                 existing_code_parts.append(f"{current_path} = {current_path} or {{}}")
            else:
                parent_path = ".".join(parts[:i])
                if parent_path and parent_path not in initialized_lua_tables and '.' not in parent_path:
                    existing_code_parts.append(f"{parent_path} = {parent_path} or {{}}")
                    initialized_lua_tables.add(parent_path)
                existing_code_parts.append(f"{parent_path}.{part} = {parent_path}.{part} or {{}}")
            initialized_lua_tables.add(current_path)

def ensure_lua_table_initialized_for_alias_parent(name: str, existing_code_parts: List[str]) -> None:
    if '.' not in name: return
    parts = name.split('.')
    parent_path_parts = parts[:-1]
    current_parent_path = ""
    for i, part in enumerate(parent_path_parts):
        if current_parent_path: current_parent_path += "." + part
        else: current_parent_path = part
        if current_parent_path not in initialized_lua_tables:
            prefix_to_assign_to = ".".join(parent_path_parts[:i])
            if not prefix_to_assign_to:
                 existing_code_parts.append(f"{current_parent_path} = {current_parent_path} or {{}}")
            else:
                existing_code_parts.append(f"{prefix_to_assign_to}.{part} = {prefix_to_assign_to}.{part} or {{}}")
            initialized_lua_tables.add(current_parent_path)

def process_enum(name: str, enum_def: Dict[str, Any]) -> str:
    values = enum_def.get("values", {})
    desc = enum_def.get("description", "")
    added_version = enum_def.get("addedVersion", "")
    examples = enum_def.get("examples", [])
    lua_assignment_parts = []
    ensure_lua_table_initialized(name, lua_assignment_parts) 
    result = format_description(desc)
    if added_version: result += f"---@version {added_version}\n"
    if examples:
        result += "--- ### Examples\n"
        for example in examples:
            example_desc = example.get("description", "")
            example_code = example.get("code", "")
            if example_desc: result += format_description(example_desc, "--- ")
            if example_code:
                result += "--- ```lua\n"
                for line in example_code.split('\n'): result += f"--- {line}\n"
                result += "--- ```\n"
    result += f"---@enum {name}\n"
    enum_table_content = f"{name} = {{\n"
    if isinstance(values, list):
        for i, val_str in enumerate(values):
            clean_key = sanitize_lua_name(val_str)
            key_repr = f'["{val_str}"]' if (not clean_key.isidentifier() or clean_key.isdigit()) else clean_key
            enum_table_content += f'    {key_repr} = "{val_str}"'
            if i < len(values) - 1: enum_table_content += ","
            enum_table_content += "\n"
    elif isinstance(values, dict):
        items = list(values.items())
        for i, (key, value) in enumerate(items):
            if not key: continue
            key_repr = f'["{key}"]' if (not str(key).isidentifier() or str(key).isdigit()) else str(key)
            if isinstance(value, str): formatted_value = f'"{value}"'
            elif isinstance(value, (int, float, bool)): formatted_value = str(value).lower() if isinstance(value, bool) else str(value)
            else: formatted_value = f'"{str(value)}"'
            enum_table_content += f"    {key_repr} = {formatted_value}"
            if i < len(items) - 1: enum_table_content += ","
            enum_table_content += "\n"
    if not values: enum_table_content += "    -- _EMPTY_ENUM_ = true\n"
    enum_table_content += "}\n"
    return "\n".join(lua_assignment_parts) + "\n" + result + enum_table_content

def process_class_like_definition(name: str, def_data: Dict[str, Any], schema: Dict[str, Any], is_global_declaration: bool) -> str:
    if name in processed_types:
        if is_global_declaration: 
            lua_assignment_parts = []
            if name not in initialized_lua_tables and '.' not in name:
                 lua_assignment_parts.append(f"{name} = {name} or {{}}")
                 initialized_lua_tables.add(name)
            if lua_assignment_parts:
                return "\n".join(lua_assignment_parts) + f"\n -- {name} @class already processed, ensuring global table existence\n"
        return "" 
    processed_types.add(name) 
    kind = def_data.get("kind", "record")
    desc = def_data.get("description", "")
    added_version = def_data.get("addedVersion", "")
    inherits = def_data.get("inherits", [])
    examples = def_data.get("examples", [])
    if isinstance(inherits, str) and inherits: inherits = [inherits]
    class_annotation_block = format_description(desc)
    if added_version and (not is_global_declaration or not (def_data.get("static") or def_data.get("instance"))):
         class_annotation_block += f"---@version {added_version}\n"
    if examples:
        class_annotation_block += "--- ### Examples\n"
        for example in examples:
            example_desc = example.get("description", "")
            example_code = example.get("code", "")
            if example_desc: class_annotation_block += format_description(example_desc, "--- ")
            if example_code:
                class_annotation_block += "--- ```lua\n"
                for line in example_code.split('\n'): class_annotation_block += f"--- {line}\n"
                class_annotation_block += "--- ```\n"
    class_annotation_block += f"---@class {name}"
    if inherits: class_annotation_block += f" : {', '.join(map_type(inh) for inh in inherits)}"
    class_annotation_block += "\n"
    instance_properties = def_data.get("properties", {})
    if not instance_properties and "fields" in def_data: 
        instance_properties = def_data.get("fields", {})
    for prop_name, prop_def in instance_properties.items():
        prop_type_val = prop_def.get("type", "any")
        prop_desc = prop_def.get("description", "")
        prop_optional = prop_def.get("optional", False)
        prop_readonly = prop_def.get("readonly", False)
        prop_version = prop_def.get("addedVersion", "")
        prop_examples = prop_def.get("examples", [])
        lua_prop_name = sanitize_lua_name(prop_name)
        if prop_optional: lua_prop_name += "?"
        type_str = map_type(prop_type_val)
        field_line = f"---@field {lua_prop_name} {type_str}"
        if prop_readonly: field_line += " #READONLY"
        if prop_desc: field_line += format_multiline_annotation_desc(prop_desc)
        if prop_version: field_line += f" @version {prop_version}"
        current_field_lines = [field_line]
        if prop_examples:
            current_field_lines.append("\n--- ### Examples:")
            for ex_idx, ex in enumerate(prop_examples):
                ex_desc = ex.get("description", "")
                ex_code = ex.get("code", "")
                if ex_desc: current_field_lines.append(format_description(f"Example {ex_idx+1}: {ex_desc}", "--- ").strip())
                if ex_code:
                    current_field_lines.append("--- ```lua")
                    for line in ex_code.split('\n'): current_field_lines.append(f"--- {line}")
                    current_field_lines.append("--- ```")
        class_annotation_block += "\n".join(current_field_lines) + "\n"
    static_members = def_data.get("static", {})
    for static_name, static_def in static_members.items():
        static_type_val = static_def.get("type", "any")
        static_desc = static_def.get("description", "")
        static_version = static_def.get("addedVersion", "")
        static_readonly = static_def.get("readonly", False)
        static_examples = static_def.get("examples", [])
        lua_static_name = sanitize_lua_name(static_name)
        type_str_for_field = map_type(static_type_val)
        if "params" in static_def or "returns" in static_def: 
            type_str_for_field = generate_fun_signature_for_field(static_def)
        field_line = f"---@field {lua_static_name} {type_str_for_field}"
        if static_readonly: field_line += " #READONLY"
        if static_desc: field_line += format_multiline_annotation_desc(static_desc)
        if static_version: field_line += f" @version {static_version}"
        current_field_lines = [field_line]
        if static_examples:
            current_field_lines.append("\n--- ### Examples:")
            for ex_idx, ex in enumerate(static_examples):
                ex_desc = ex.get("description", "")
                ex_code = ex.get("code", "")
                if ex_desc: current_field_lines.append(format_description(f"Example {ex_idx+1}: {ex_desc}", "--- ").strip())
                if ex_code:
                    current_field_lines.append("--- ```lua")
                    for line in ex_code.split('\n'): current_field_lines.append(f"--- {line}")
                    current_field_lines.append("--- ```")
        class_annotation_block += "\n".join(current_field_lines) + "\n"
    lua_assignment_parts = []
    ensure_lua_table_initialized(name, lua_assignment_parts)
    lua_assignment_code = "\n".join(lua_assignment_parts) + "\n" if lua_assignment_parts else ""
    if not is_global_declaration and '.' not in name and name not in initialized_lua_tables:
        if not (def_data.get("static") or def_data.get("instance")):
            lua_assignment_code += f"{name} = {{}}\n"
            initialized_lua_tables.add(name)
    method_definitions_parts = []
    instance_methods_schema = def_data.get("instance", {})
    if not instance_methods_schema and (kind == "class" or not is_global_declaration):
         instance_methods_schema = def_data.get("methods", {})
    for method_name, method_def_val in instance_methods_schema.items():
        current_method_def = method_def_val[0] if isinstance(method_def_val, list) and method_def_val else method_def_val
        if not current_method_def: continue
        method_definitions_parts.append(process_method(name, method_name, current_method_def))
    static_methods_schema = def_data.get("static", {})
    for func_name, func_def_val in static_methods_schema.items():
        current_func_def = func_def_val[0] if isinstance(func_def_val, list) and func_def_val else func_def_val
        if not current_func_def: continue
        if "params" in current_func_def or "returns" in current_func_def: 
            method_definitions_parts.append(process_static_function(name, func_name, current_func_def))
    return f"{class_annotation_block}{lua_assignment_code}{''.join(method_definitions_parts)}"

def process_type_definition(name: str, type_def: Dict[str, Any], schema: Dict[str, Any]) -> str:
    if name in processed_types:
        return ""

    kind = type_def.get("kind")
    desc = type_def.get("description", "")
    added_version = type_def.get("addedVersion", "")
    examples = type_def.get("examples", [])
    fields = type_def.get("fields", {})

    header_block = format_description(desc)
    if added_version:
        header_block += f"---@version {added_version}\n"
    if examples:
        header_block += "--- ### Examples\n"
        for example in examples:
            example_desc = example.get("description", "")
            example_code = example.get("code", "")
            if example_desc: header_block += format_description(example_desc, "--- ")
            if example_code:
                header_block += "--- ```lua\n"
                for line in example_code.split('\n'): header_block += f"--- {line}\n"
                header_block += "--- ```\n"

    if kind == "enum":
        processed_types.add(name)
        return process_enum(name, type_def)

    if '.' in name: # Dot-notated types from 'types' section are treated as class-like (records/namespaces)
        return process_class_like_definition(name, type_def, schema, False)

    # For non-dot.notated types from schema.types:
    if kind == "array":
        processed_types.add(name)
        array_of_type = type_def.get("arrayOf", "any")
        mapped_array_of_type = map_type(array_of_type)
        alias_definition = f"---@alias {name} {mapped_array_of_type}[]\n"
        return f"{header_block}{alias_definition}"

    elif kind == "union":
        processed_types.add(name)
        union_of_types = type_def.get("anyOf", [])
        if not union_of_types: mapped_union_str = "any"
        else:
            mapped_union_types = sorted(list(set(map_type(t) for t in union_of_types)))
            mapped_union_str = "|".join(mapped_union_types)
        alias_definition = f"---@alias {name} {mapped_union_str}\n"
        return f"{header_block}{alias_definition}"

    elif kind == "record":
        processed_types.add(name)
        # Top-level 'record' from 'types' section becomes an alias for a table shape
        # if it doesn't have 'instance' or 'static' sections (i.e., it's a pure data structure definition).
        if not type_def.get("instance") and not type_def.get("static"):
            alias_table_shape_parts = ["{"] # Start of the table literal
            if fields:
                field_items = list(fields.items())
                for i, (field_name, field_def) in enumerate(field_items):
                    field_type_str = map_type(field_def.get("type", "any"))
                    lua_field_key = sanitize_lua_name(field_name)
                    # Quote if not a simple identifier or if it could be a Lua keyword
                    if not lua_field_key.isidentifier() or \
                       lua_field_key in {"type", "function", "end", "local", "then", "if", "else", "elseif",
                                          "for", "while", "do", "repeat", "until", "break", "goto", "and", "or", "not",
                                          "return", "in"}: # Expanded keyword list
                        lua_field_key = f'["{field_name}"]'
                    
                    field_optional_char = "?" if field_def.get("optional") else ""
                    
                    field_desc_short = ""
                    f_desc = field_def.get("description", "")
                    if f_desc:
                        first_line_f_desc = f_desc.split('\n')[0].strip()
                        if first_line_f_desc: # Only add comment if description exists
                             field_desc_short = f" # {first_line_f_desc}"
                    
                    # Add to parts: field_key?: field_type, # optional_comment
                    alias_table_shape_parts.append(f"  {lua_field_key}{field_optional_char}: {field_type_str}{field_desc_short}")
                    if i < len(field_items) - 1:
                        alias_table_shape_parts[-1] += "," # Add comma if not the last field
            
            alias_table_shape_parts.append("}") # End of the table literal
            
            alias_table_shape_str = ""
            if len(alias_table_shape_parts) > 2 : # Has fields (more than just '{' and '}')
                # Format for multi-line alias table shape:
                # ---@alias MyType
                # ---    {
                # ---      field1: type, # desc
                # ---      field2: type  # desc
                # ---    }
                # ---
                alias_table_shape_str = "\n---\t" + "\n---\t".join(alias_table_shape_parts) + "\n---"
            else: # Empty record
                alias_table_shape_str = "{}" # e.g. ---@alias MyEmptyRecord {}
            
            alias_definition = f"---@alias {name} {alias_table_shape_str}\n"
            return f"{header_block}{alias_definition}"
        else: # Record with instance/static is treated as a class
            return process_class_like_definition(name, type_def, schema, False)

    elif kind == "class": 
        return process_class_like_definition(name, type_def, schema, False)

    processed_types.add(name)
    unknown_kind_class_def = f"---@class {name}\n"
    table_init_for_unknown = ""
    if '.' not in name and name not in initialized_lua_tables:
        table_init_for_unknown = f"{name} = {name} or {{}}\n"
        initialized_lua_tables.add(name)
    return f"{header_block}--- Fallback: Unhandled type kind '{kind}' for type '{name}'. Treating as class.\n{unknown_kind_class_def}{table_init_for_unknown}"

def export_to_lua(schema: Dict[str, Any], output_path: str) -> None:
    output_dir = os.path.dirname(output_path)
    if output_dir: os.makedirs(output_dir, exist_ok=True)
    source_file_name = "unknown_schema.json"
    if 'source_file_path' in schema and schema['source_file_path']:
        source_file_name = os.path.basename(schema['source_file_path'])
    header_info = [
        "--[[ DCS World Lua Type Definitions",
        f"Generated from schema: {source_file_name}",
        "DO NOT MODIFY - AUTO-GENERATED FILE",
        f"Generated on: {datetime.datetime.now().isoformat()}",
        "--]]",
        "",
        "---@meta",
        "",
    ]
    output_content_parts = []
    processed_types.clear()
    initialized_lua_tables.clear()
    if "globals" in schema:
        output_content_parts.append("-- Global Namespaces and Classes")
        for global_name, global_def in sorted(schema["globals"].items()):
            output_content_parts.append(process_class_like_definition(global_name, global_def, schema, True))
    types_to_process_tuples = []
    if "types" in schema:
        non_namespaced_types = []
        namespaced_types = []
        for name, definition in schema["types"].items():
            if "." not in name: non_namespaced_types.append((name, definition))
            else: namespaced_types.append((name, definition))
        non_namespaced_types.sort(key=lambda item: item[0])
        namespaced_types.sort(key=lambda item: (len(item[0].split('.')), item[0]))
        types_to_process_tuples = non_namespaced_types + namespaced_types
        output_content_parts.append("\n-- Type Definitions (Enums, Aliases, Records/Classes)")
        for type_name, type_def in types_to_process_tuples:
            if type_name not in processed_types:
                 output_content_parts.append(process_type_definition(type_name, type_def, schema))
    full_output_content = "\n".join(header_info + [part for part in output_content_parts if part and part.strip()])
    with open(output_path, "w", encoding="utf-8") as f: f.write(full_output_content)
    print(f"Lua type definitions exported to {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Export DCS schema to Lua EmmyLua annotations")
    parser.add_argument("schema_file", help="Path to the DCS schema JSON file")
    parser.add_argument("--output", "-o", default="dist/dcs-world-api.lua", help="Output Lua definition file")
    args = parser.parse_args()
    try:
        schema_data = load_schema(args.schema_file)
        schema_data['source_file_path'] = args.schema_file 
        export_to_lua(schema_data, args.output)
    except Exception as e:
        print(f"Error processing schema {args.schema_file}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()