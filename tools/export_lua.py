#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Set, Union, Tuple
import datetime
from collections import deque

# LUA primitive type mapping
TYPE_MAPPING = {
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "table": "table",
    "function": "fun(...)", # EmmyLua convention for generic function
    "any": "any",
    "nil": "nil",
    "void": "nil", # Changed from "void" to "nil" for EmmyLua consistency
}

PRIMITIVE_LUA_TYPES = set(TYPE_MAPPING.values())

# Track processed types to avoid re-defining ---@class/---@alias/---@enum annotations
processed_types: Set[str] = set()
# Track globals/namespaces for which Lua tables have been initialized
initialized_lua_tables: Set[str] = set()


def load_schema(path: str) -> Dict[str, Any]:
    """
    Load the schema from a JSON file.

    :param path: Path to the JSON schema file.
    :type path: str
    :raises FileNotFoundError: If the schema file does not exist.
    :raises json.JSONDecodeError: If the schema file is not valid JSON.
    :returns: The loaded schema as a dictionary.
    :rtype: Dict[str, Any]
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_lua_name(name: str) -> str:
    """
    Make a name safe for Lua, e.g., for parameters or local variables.
    Replaces special characters and prepends an underscore if it's a Lua keyword.

    :param name: The name to sanitize.
    :type name: str
    :returns: A Lua-safe version of the name.
    :rtype: str
    """
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
    """
    Map DCS schema type to Lua type annotation for EmmyLua.

    Handles primitive types, union types (represented as lists or pipe-separated strings),
    array types (e.g., 'MyType[]'), and map types (e.g., 'map<string, number>').

    :param type_str: The type string or list of type strings from the schema.
    :type type_str: Union[str, List[str]]
    :returns: The EmmyLua-compatible type string.
    :rtype: str
    """
    if isinstance(type_str, list): # For union types represented as a list
        return "|".join(sorted(list(set(map_type(t) for t in type_str))))

    if not type_str:
        return "any"
    
    original_type_str = type_str.strip()

    if "|" in original_type_str:
        types = [map_type(t.strip()) for t in original_type_str.split("|")]
        return "|".join(sorted(list(set(types))))
    if original_type_str.endswith("[]"):
        base_type = original_type_str[:-2].strip()
        return f"{map_type(base_type)}[]"
    if original_type_str.startswith("map<") and original_type_str.endswith(">"):
        inner_content = original_type_str[4:-1].strip()
        parts = inner_content.split(",", 1)
        if len(parts) == 2:
            key_type = map_type(parts[0].strip())
            value_type = map_type(parts[1].strip())
            return f"table<{key_type}, {value_type}>"
        else: 
            return f"table<any, {map_type(inner_content)}>"
    if original_type_str in TYPE_MAPPING:
        return TYPE_MAPPING[original_type_str]
    return original_type_str # Assume it's a custom type


def format_description(desc: str, indent: str = "") -> str:
    """
    Format a description string as a block of EmmyLua comments.

    Each line of the description is prefixed with '--- ' and the specified indent.

    :param desc: The description string.
    :type desc: str
    :param indent: An optional indent string to prefix each comment line (after '--- ').
    :type indent: str
    :returns: The formatted comment block.
    :rtype: str
    """
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
    """
    Formats a multi-line description to be appended to an EmmyLua annotation line.
    The first line is appended directly, subsequent lines are prefixed with '--- '.

    :param description: The description string.
    :type description: str
    :returns: The formatted description string for annotation.
    :rtype: str
    """
    if not description:
        return ""
    lines = description.strip().split('\n')
    if not lines:
        return ""
    formatted = " " + lines[0].strip() # Add space before the first line
    if len(lines) > 1:
        for i in range(1, len(lines)):
            stripped_line = lines[i].strip()
            if stripped_line: # Only add if the line is not empty
                formatted += f"\n--- {stripped_line}"
    return formatted


def process_param_for_annotation(param: Dict[str, Any]) -> str:
    """
    Processes a single parameter definition into an EmmyLua @param annotation.

    :param param: A dictionary representing the parameter's schema definition.
    :type param: Dict[str, Any]
    :returns: A string for the ---@param annotation.
    :rtype: str
    """
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
    """
    Generates a Lua function signature string for use in ---@field type annotations.
    Example: fun(param1:type1, param2?:type2):returnType or fun():(ret1, ret2)

    :param func_def: The function's schema definition.
    :type func_def: Dict[str, Any]
    :returns: A string representing the function signature.
    :rtype: str
    """
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
            if isinstance(ret_item, str):
                ret_type_str_val = map_type(ret_item)
            elif isinstance(ret_item, dict): 
                ret_type_str_val = map_type(ret_item.get("type", "any"))
            
            if ret_type_str_val and ret_type_str_val != "nil":
                actual_returns_for_fun_sig.append(ret_type_str_val)
            elif ret_type_str_val == "nil": 
                 actual_returns_for_fun_sig.append("nil")


    if not actual_returns_for_fun_sig:
        return_signature_for_fun = "void" 
    elif len(actual_returns_for_fun_sig) == 1:
        return_signature_for_fun = actual_returns_for_fun_sig[0]
    else:
        return_signature_for_fun = f"({', '.join(actual_returns_for_fun_sig)})"

    return f"fun({', '.join(param_signatures)}):{return_signature_for_fun}"


def process_function_common(class_name_or_nil: Union[str, None], func_name: str, func_def: Dict[str, Any], is_static: bool) -> str:
    """
    Common logic for processing a function (method or static function) definition.
    Generates the full EmmyLua annotation block and the function stub.

    :param class_name_or_nil: The name of the class/table if it's a method/static function, else None.
    :type class_name_or_nil: Union[str, None]
    :param func_name: The name of the function.
    :type func_name: str
    :param func_def: The schema definition of the function.
    :type func_def: Dict[str, Any]
    :param is_static: True if the function is static, False for instance methods.
    :type is_static: bool
    :returns: The EmmyLua string for the function.
    :rtype: str
    """
    params_list = func_def.get("params", [])
    returns_list = func_def.get("returns", [])
    desc = func_def.get("description", "")
    added_version = func_def.get("addedVersion", "")
    examples = func_def.get("examples", [])

    result = format_description(desc)
    if added_version:
        result += f"---@version {added_version}\n"

    for param_def in params_list:
        result += process_param_for_annotation(param_def) + "\n"

    actual_returns_for_annotation = []
    if isinstance(returns_list, str): 
        mapped_ret = map_type(returns_list)
        if mapped_ret != "nil": 
            actual_returns_for_annotation.append(mapped_ret)
    elif isinstance(returns_list, list): 
        for ret_item in returns_list:
            ret_type_str_val = ""
            if isinstance(ret_item, str):
                ret_type_str_val = map_type(ret_item)
            elif isinstance(ret_item, dict):
                ret_type_str_val = map_type(ret_item.get("type", "any"))
            
            if ret_type_str_val: 
                actual_returns_for_annotation.append(ret_type_str_val)
    
    if not (len(actual_returns_for_annotation) == 1 and actual_returns_for_annotation[0] == "nil" and not returns_list): 
        for ret_type_str_val in actual_returns_for_annotation:
            result += f"---@return {ret_type_str_val}\n"
            
    if examples:
        result += "--- ### Examples\n"
        for example in examples:
            example_desc = example.get("description", "")
            example_code = example.get("code", "")
            if example_desc:
                result += format_description(example_desc, "--- ")
            if example_code:
                result += "--- ```lua\n"
                for line in example_code.split('\n'):
                    result += f"--- {line}\n"
                result += "--- ```\n"

    sanitized_params_for_sig = [sanitize_lua_name(p.get("name", f"arg{i+1}")) for i, p in enumerate(params_list)]
    
    lua_func_name = sanitize_lua_name(func_name)
    if lua_func_name != func_name and (not hasattr(func_name, 'isidentifier') or not func_name.isidentifier() or func_name in TYPE_MAPPING.keys()):
        lua_func_name = f'["{func_name}"]'


    separator = "." if is_static else ":"
    if class_name_or_nil:
        result += f"function {class_name_or_nil}{separator}{lua_func_name}({', '.join(sanitized_params_for_sig)}) end\n\n"
    else: 
        result += f"function {lua_func_name}({', '.join(sanitized_params_for_sig)}) end\n\n"
    return result

def process_method(class_name: str, method_name: str, method_def: Dict[str, Any]) -> str:
    """
    Processes an instance method definition.

    :param class_name: The name of the class.
    :type class_name: str
    :param method_name: The name of the method.
    :type method_name: str
    :param method_def: The schema definition of the method.
    :type method_def: Dict[str, Any]
    :returns: The EmmyLua string for the method.
    :rtype: str
    """
    return process_function_common(class_name, method_name, method_def, is_static=False)

def process_static_function(class_name: str, func_name: str, func_def: Dict[str, Any]) -> str:
    """
    Processes a static function definition for a class/table.

    :param class_name: The name of the class/table.
    :type class_name: str
    :param func_name: The name of the static function.
    :type func_name: str
    :param func_def: The schema definition of the static function.
    :type func_def: Dict[str, Any]
    :returns: The EmmyLua string for the static function.
    :rtype: str
    """
    return process_function_common(class_name, func_name, func_def, is_static=True)


def ensure_lua_table_initialized(name: str, existing_code_parts: List[str]) -> None:
    """
    Ensures that Lua tables for namespaces are initialized (e.g., AI = AI or {}).
    Adds initialization code to `existing_code_parts` if not already processed.

    :param name: The potentially dot-separated name of the table/namespace.
    :type name: str
    :param existing_code_parts: A list of strings to which initialization code will be appended.
    :type existing_code_parts: List[str]
    """
    parts = name.split('.')
    current_path = ""
    for i, part in enumerate(parts):
        if current_path:
            current_path += "." + part
        else:
            current_path = part
        
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
    """
    Ensures that parent Lua tables for a namespaced alias are initialized.
    This is for aliases that might be defined before their parent namespace table.

    :param name: The dot-separated name of the alias.
    :type name: str
    :param existing_code_parts: A list of strings to which initialization code will be appended.
    :type existing_code_parts: List[str]
    """
    if '.' not in name:
        return 

    parts = name.split('.')
    parent_path_parts = parts[:-1] 
    current_parent_path = ""

    for i, part in enumerate(parent_path_parts):
        if current_parent_path:
            current_parent_path += "." + part
        else:
            current_parent_path = part
        
        if current_parent_path not in initialized_lua_tables:
            prefix_to_assign_to = ".".join(parent_path_parts[:i]) 
            if not prefix_to_assign_to: 
                 existing_code_parts.append(f"{current_parent_path} = {current_parent_path} or {{}}")
            else:
                existing_code_parts.append(f"{prefix_to_assign_to}.{part} = {prefix_to_assign_to}.{part} or {{}}")
            initialized_lua_tables.add(current_parent_path)


def process_enum(name: str, enum_def: Dict[str, Any]) -> str:
    """
    Processes an enum definition from the schema.

    :param name: The name of the enum.
    :type name: str
    :param enum_def: The schema definition of the enum.
    :type enum_def: Dict[str, Any]
    :returns: The EmmyLua string for the enum.
    :rtype: str
    """
    values = enum_def.get("values", {})
    desc = enum_def.get("description", "")
    added_version = enum_def.get("addedVersion", "")
    examples = enum_def.get("examples", [])

    lua_assignment_parts = []
    ensure_lua_table_initialized(name, lua_assignment_parts) 

    result = format_description(desc)
    if added_version:
        result += f"---@version {added_version}\n"
    
    if examples:
        result += "--- ### Examples\n"
        for example in examples:
            example_desc = example.get("description", "")
            example_code = example.get("code", "")
            if example_desc:
                result += format_description(example_desc, "--- ")
            if example_code:
                result += "--- ```lua\n"
                for line in example_code.split('\n'):
                    result += f"--- {line}\n"
                result += "--- ```\n"

    result += f"---@enum {name}\n"
    
    enum_table_content = f"{name} = {{\n"
    if isinstance(values, list): 
        for i, val_str in enumerate(values):
            clean_key = sanitize_lua_name(val_str)
            key_repr = f'["{val_str}"]' if (not clean_key.isidentifier() or clean_key.isdigit()) else clean_key
            enum_table_content += f'    {key_repr} = "{val_str}"' 
            if i < len(values) - 1:
                enum_table_content += ","
            enum_table_content += "\n"
    elif isinstance(values, dict): 
        items = list(values.items())
        for i, (key, value) in enumerate(items):
            if not key: continue 

            key_repr = f'["{key}"]' if (not str(key).isidentifier() or str(key).isdigit()) else str(key)

            if isinstance(value, str):
                formatted_value = f'"{value}"'
            elif isinstance(value, (int, float, bool)):
                formatted_value = str(value).lower() if isinstance(value, bool) else str(value)
            else: 
                formatted_value = f'"{str(value)}"'
            enum_table_content += f"    {key_repr} = {formatted_value}"
            if i < len(items) - 1:
                enum_table_content += ","
            enum_table_content += "\n"
            
    if not values: 
        enum_table_content += "    -- _EMPTY_ENUM_ = true\n" 

    enum_table_content += "}\n"

    return "\n".join(lua_assignment_parts) + "\n" + result + enum_table_content


def process_class_like_definition(name: str, def_data: Dict[str, Any], schema: Dict[str, Any], is_global_declaration: bool) -> str:
    """
    Processes a class-like definition (class, singleton, or complex record/table).
    Generates ---@class annotation, fields, and method/static function stubs.

    :param name: The name of the class/table.
    :type name: str
    :param def_data: The schema definition for this item.
    :type def_data: Dict[str, Any]
    :param schema: The full schema (used for resolving type references if needed).
    :type schema: Dict[str, Any]
    :param is_global_declaration: True if this is a top-level global, False if it's from the 'types' section or nested.
    :type is_global_declaration: bool
    :returns: The EmmyLua string for the class-like definition.
    :rtype: str
    """
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

    if isinstance(inherits, str) and inherits: 
        inherits = [inherits]

    class_annotation_block = format_description(desc)
    if added_version and (not is_global_declaration or not (def_data.get("static") or def_data.get("instance"))):
         class_annotation_block += f"---@version {added_version}\n"

    if examples:
        class_annotation_block += "--- ### Examples\n"
        for example in examples:
            example_desc = example.get("description", "")
            example_code = example.get("code", "")
            if example_desc:
                class_annotation_block += format_description(example_desc, "--- ")
            if example_code:
                class_annotation_block += "--- ```lua\n"
                for line in example_code.split('\n'):
                    class_annotation_block += f"--- {line}\n"
                class_annotation_block += "--- ```\n"
    
    class_annotation_block += f"---@class {name}"
    if inherits:
        class_annotation_block += f" : {', '.join(map_type(inh) for inh in inherits)}"
    class_annotation_block += "\n"

    instance_properties = def_data.get("properties", {})
    if not instance_properties and "fields" in def_data: 
        instance_properties = def_data.get("fields", {})

    for prop_name, prop_def in instance_properties.items():
        prop_type_val = prop_def.get("type", "any")
        prop_desc_val = prop_def.get("description", "")
        prop_optional = prop_def.get("optional", False)
        prop_readonly = prop_def.get("readonly", False)
        prop_version_val = prop_def.get("addedVersion", "")
        prop_examples_list = prop_def.get("examples", [])

        lua_prop_name = sanitize_lua_name(prop_name)
        if prop_optional:
            lua_prop_name += "?"
        type_str = map_type(prop_type_val)
        
        field_line = f"---@field {lua_prop_name} {type_str}"
        if prop_readonly:
            field_line += " #READONLY"
        
        current_field_lines = []
        if prop_desc_val:
            field_line += format_multiline_annotation_desc(prop_desc_val)
        
        if prop_version_val: 
            if not prop_desc_val and not prop_readonly:
                 field_line += " " 
            field_line += f"@version {prop_version_val}" 
        
        current_field_lines.append(field_line)

        if prop_examples_list:
            current_field_lines.append("--- ### Examples:") 
            for ex_idx, ex in enumerate(prop_examples_list):
                ex_desc = ex.get("description", "")
                ex_code = ex.get("code", "")
                if ex_desc:
                    current_field_lines.append(format_description(f"Example {ex_idx+1}: {ex_desc}", "--- ").strip())
                if ex_code:
                    current_field_lines.append("--- ```lua")
                    for line in ex_code.split('\n'):
                        current_field_lines.append(f"--- {line}")
                    current_field_lines.append("--- ```")
        class_annotation_block += "\n".join(current_field_lines) + "\n"

    static_members = def_data.get("static", {})
    for static_name, static_def in static_members.items():
        if "params" in static_def or "returns" in static_def and static_def.get("kind") != "enum": 
            continue 

        static_type_val = static_def.get("type", "any")
        static_desc_val = static_def.get("description", "")
        static_version_val = static_def.get("addedVersion", "")
        static_readonly = static_def.get("readonly", False)
        static_examples_list = static_def.get("examples", [])

        lua_static_name = sanitize_lua_name(static_name)
        type_str_for_field = map_type(static_type_val)
        
        field_line = f"---@field {lua_static_name} {type_str_for_field}"
        if static_readonly:
            field_line += " #READONLY"
        
        current_field_lines = []
        if static_desc_val:
            field_line += format_multiline_annotation_desc(static_desc_val)
        if static_version_val:
            if not static_desc_val and not static_readonly: field_line += " "
            field_line += f"@version {static_version_val}"
        
        current_field_lines.append(field_line)

        if static_examples_list:
            current_field_lines.append("--- ### Examples:")
            for ex_idx, ex in enumerate(static_examples_list):
                ex_desc = ex.get("description", "")
                ex_code = ex.get("code", "")
                if ex_desc:
                    current_field_lines.append(format_description(f"Example {ex_idx+1}: {ex_desc}", "--- ").strip())
                if ex_code:
                    current_field_lines.append("--- ```lua")
                    for line in ex_code.split('\n'):
                        current_field_lines.append(f"--- {line}")
                    current_field_lines.append("--- ```")
        class_annotation_block += "\n".join(current_field_lines) + "\n"

    lua_assignment_parts = []
    if is_global_declaration or '.' in name:
        ensure_lua_table_initialized(name, lua_assignment_parts)
    
    lua_assignment_code = "\n".join(lua_assignment_parts) + "\n" if lua_assignment_parts else ""
    
    if not is_global_declaration and '.' not in name:
        if not (def_data.get("static") or def_data.get("instance") or def_data.get("methods")):
            lua_assignment_code = "" 
            if name in initialized_lua_tables: 
                pass 

    method_definitions_parts = []

    instance_methods_schema = def_data.get("instance", {})
    if not instance_methods_schema and (kind == "class" or not is_global_declaration): 
         instance_methods_schema = def_data.get("methods", {}) 

    for method_name, method_def_val in instance_methods_schema.items():
        current_method_def = method_def_val[0] if isinstance(method_def_val, list) and method_def_val else method_def_val
        if not current_method_def or not isinstance(current_method_def, dict): continue 
        method_definitions_parts.append(process_method(name, method_name, current_method_def))

    static_definitions_schema = def_data.get("static", {}) 
    for func_name, func_def_val in static_definitions_schema.items():
        current_func_def = func_def_val[0] if isinstance(func_def_val, list) and func_def_val else func_def_val
        if not current_func_def or not isinstance(current_func_def, dict): continue

        if ("params" in current_func_def or "returns" in current_func_def) and current_func_def.get("kind") != "enum": 
            method_definitions_parts.append(process_static_function(name, func_name, current_func_def))
            
    return f"{class_annotation_block}{lua_assignment_code}{''.join(method_definitions_parts)}"

def process_type_definition(name: str, type_def: Dict[str, Any], schema: Dict[str, Any]) -> str:
    """
    Processes a single type definition from the schema's 'types' section.
    Handles enums, arrays, unions, and records.
    Pure records (data structures without methods/statics) are converted to `---@class`
    with a semantic note for better IDE tooling.

    :param name: The name of the type.
    :type name: str
    :param type_def: The schema definition for this type.
    :type type_def: Dict[str, Any]
    :param schema: The full schema.
    :type schema: Dict[str, Any]
    :returns: The EmmyLua string for the type definition.
    :rtype: str
    """
    if name in processed_types:
        return "" 

    kind = type_def.get("kind")
    desc = type_def.get("description", "")
    added_version = type_def.get("addedVersion", "")
    examples = type_def.get("examples", [])
    fields = type_def.get("fields", {})

    if kind == "record" and \
       not type_def.get("instance") and \
       not type_def.get("static") and \
       not type_def.get("methods") and \
       '.' not in name: 

        processed_types.add(name)
        output_parts = []

        original_desc_text = desc
        semantic_note = f"(Data structure definition for {name}. Not a globally accessible table.)"
        
        enhanced_desc_text = original_desc_text
        if enhanced_desc_text and enhanced_desc_text.strip():
            enhanced_desc_text = f"{enhanced_desc_text.strip()}\n{semantic_note}"
        else:
            enhanced_desc_text = semantic_note
        
        output_parts.append(format_description(enhanced_desc_text))

        if added_version:
            output_parts.append(f"---@version {added_version}\n")

        if examples:
            output_parts.append("--- ### Examples\n")
            for example in examples:
                example_desc = example.get("description", "")
                example_code = example.get("code", "")
                if example_desc: output_parts.append(format_description(example_desc, "--- "))
                if example_code:
                    output_parts.append("--- ```lua\n")
                    for line in example_code.split('\n'): output_parts.append(f"--- {line}\n")
                    output_parts.append("--- ```\n")
        
        output_parts.append(f"---@class {name}\n")

        if fields:
            for field_name, field_def_val in fields.items():
                field_type_str = map_type(field_def_val.get("type", "any"))
                lua_field_key = sanitize_lua_name(field_name)
                field_optional_char = "?" if field_def_val.get("optional") else ""
                
                field_description_val = field_def_val.get("description", "")
                field_version_val = field_def_val.get("addedVersion", "")
                field_readonly_val = field_def_val.get("readonly", False)
                
                field_annotation_line = f"---@field {lua_field_key}{field_optional_char} {field_type_str}"
                
                if field_readonly_val:
                    field_annotation_line += " #READONLY"
                
                if field_description_val:
                    field_annotation_line += format_multiline_annotation_desc(field_description_val)
                
                if field_version_val:
                    if not field_description_val and not field_readonly_val:
                         field_annotation_line += " " 
                    field_annotation_line += f"@version {field_version_val}"

                output_parts.append(field_annotation_line + "\n")
        
        return "".join(output_parts)

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

    if '.' in name: 
        if kind == "enum": 
             processed_types.add(name)
             return process_enum(name, type_def)
        return process_class_like_definition(name, type_def, schema, False)


    if kind == "array":
        processed_types.add(name)
        array_of_type = type_def.get("arrayOf", "any")
        mapped_array_of_type = map_type(array_of_type)
        alias_definition = f"---@alias {name} {mapped_array_of_type}[]\n"
        return f"{header_block}{alias_definition}"

    elif kind == "union":
        processed_types.add(name)
        union_of_types = type_def.get("anyOf", [])
        if not union_of_types:
            mapped_union_str = "any"
        else:
            mapped_union_types = sorted(list(set(map_type(t) for t in union_of_types)))
            mapped_union_str = "|".join(mapped_union_types)
        alias_definition = f"---@alias {name} {mapped_union_str}\n"
        return f"{header_block}{alias_definition}"

    elif kind == "record": 
        return process_class_like_definition(name, type_def, schema, False)
    
    elif kind == "class": 
        return process_class_like_definition(name, type_def, schema, False)

    processed_types.add(name)
    unknown_kind_def = f"--- Fallback: Unhandled type kind '{kind}' for type '{name}'.\n"
    return f"{header_block}{unknown_kind_def}"

def get_dependencies_from_type_str(type_str_val: Union[str, List[str]], all_defined_type_names: Set[str]) -> Set[str]:
    """
    Extracts non-primitive dependency type names from a type string.
    Handles unions, arrays, and table<k,v> syntax.

    :param type_str_val: The type string or list of type strings.
    :type type_str_val: Union[str, List[str]]
    :param all_defined_type_names: A set of all custom type names defined in the schema.
    :type all_defined_type_names: Set[str]
    :returns: A set of dependency type names.
    :rtype: Set[str]
    """
    dependencies = set()
    if isinstance(type_str_val, list):
        for item in type_str_val:
            dependencies.update(get_dependencies_from_type_str(item, all_defined_type_names))
        return dependencies

    if not isinstance(type_str_val, str):
        return dependencies

    # Split unions first
    parts = type_str_val.split('|')
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Handle arrays: extract base type
        if part.endswith("[]"):
            part = part[:-2].strip()
        
        # Handle table<key, value> and table<value>
        if part.startswith("table<") and part.endswith(">"):
            inner_content = part[len("table<"):-1].strip()
            # Simple split by comma, then recurse on parts
            table_parts = inner_content.split(",", 1)
            for tp in table_parts:
                dependencies.update(get_dependencies_from_type_str(tp.strip(), all_defined_type_names))
            continue # Skip adding 'table' itself as a dependency

        # Check if the cleaned part is a defined custom type and not a primitive
        if part in all_defined_type_names and part not in PRIMITIVE_LUA_TYPES and part != "fun(...)":
            dependencies.add(part)
    return dependencies

def get_item_dependencies(item_name: str, item_def: Dict[str, Any], all_defined_type_names: Set[str]) -> Set[str]:
    """
    Gets all direct non-primitive type dependencies for a given schema item.

    :param item_name: The name of the item (class, type, etc.).
    :type item_name: str
    :param item_def: The schema definition of the item.
    :type item_def: Dict[str, Any]
    :param all_defined_type_names: A set of all custom type names defined in the schema.
    :type all_defined_type_names: Set[str]
    :returns: A set of dependency type names.
    :rtype: Set[str]
    """
    dependencies: Set[str] = set()

    # Dependencies from 'inherits'
    inherits = item_def.get("inherits", [])
    if isinstance(inherits, str): inherits = [inherits]
    for inherited_type in inherits:
        dependencies.update(get_dependencies_from_type_str(inherited_type, all_defined_type_names))

    # Dependencies from 'fields' or 'properties'
    fields_to_check = item_def.get("fields", {})
    if not fields_to_check:
        fields_to_check = item_def.get("properties", {})
    
    for _, field_def in fields_to_check.items():
        if isinstance(field_def, dict) and "type" in field_def:
            dependencies.update(get_dependencies_from_type_str(field_def["type"], all_defined_type_names))

    # Dependencies from 'static' members (fields and functions)
    for _, static_def in item_def.get("static", {}).items():
        if isinstance(static_def, dict):
            if "type" in static_def: # Static field
                dependencies.update(get_dependencies_from_type_str(static_def["type"], all_defined_type_names))
            if "params" in static_def: # Static function parameters
                for param in static_def.get("params", []):
                    dependencies.update(get_dependencies_from_type_str(param.get("type", "any"), all_defined_type_names))
            if "returns" in static_def: # Static function return types
                returns = static_def.get("returns", [])
                if isinstance(returns, str): returns = [returns]
                for ret_type_obj in returns:
                    if isinstance(ret_type_obj, str):
                        dependencies.update(get_dependencies_from_type_str(ret_type_obj, all_defined_type_names))
                    elif isinstance(ret_type_obj, dict) and "type" in ret_type_obj: # Return can be list of objects with 'type'
                         dependencies.update(get_dependencies_from_type_str(ret_type_obj["type"], all_defined_type_names))


    # Dependencies from 'instance' or 'methods' (function parameters and return types)
    methods_to_check = item_def.get("instance", {})
    if not methods_to_check:
        methods_to_check = item_def.get("methods", {})

    for _, method_def_val in methods_to_check.items():
        # Method def can be a list of overloads, take the first.
        method_def = method_def_val[0] if isinstance(method_def_val, list) and method_def_val else method_def_val
        if isinstance(method_def, dict):
            for param in method_def.get("params", []):
                dependencies.update(get_dependencies_from_type_str(param.get("type", "any"), all_defined_type_names))
            
            returns = method_def.get("returns", [])
            if isinstance(returns, str): returns = [returns] # Normalize to list
            for ret_type_obj in returns: # Process each return type in the list
                if isinstance(ret_type_obj, str):
                     dependencies.update(get_dependencies_from_type_str(ret_type_obj, all_defined_type_names))
                elif isinstance(ret_type_obj, dict) and "type" in ret_type_obj:
                     dependencies.update(get_dependencies_from_type_str(ret_type_obj["type"], all_defined_type_names))


    # Dependencies from 'arrayOf' (for array types)
    if "arrayOf" in item_def:
        dependencies.update(get_dependencies_from_type_str(item_def["arrayOf"], all_defined_type_names))

    # Dependencies from 'anyOf' (for union types)
    if "anyOf" in item_def:
        for union_member_type in item_def.get("anyOf", []):
            dependencies.update(get_dependencies_from_type_str(union_member_type, all_defined_type_names))
            
    # Ensure the item itself is not listed as its own dependency directly
    dependencies.discard(item_name)
    return dependencies


def topological_sort(graph_adj: Dict[str, Set[str]]) -> List[str]:
    """
    Performs a topological sort on a graph represented by an adjacency list.
    Uses Kahn's algorithm. If a cycle is detected, it returns the successfully
    sorted part followed by the remaining nodes (involved in cycles) sorted alphabetically.

    :param graph_adj: Adjacency list where graph_adj[node] is a set of nodes that node depends on.
                      (i.e., if B is in graph_adj[A], then B must come before A).
    :type graph_adj: Dict[str, Set[str]]
    :returns: A list of nodes in topologically sorted order (or best-effort if cycles exist).
    :rtype: List[str]
    """
    in_degree = {node: 0 for node in graph_adj}
    adj_list_outgoing: Dict[str, Set[str]] = {node: set() for node in graph_adj}

    for node, dependencies in graph_adj.items():
        for dep in dependencies:
            if dep in adj_list_outgoing: 
                adj_list_outgoing[dep].add(node)
            # Increment in_degree even if dep is not in graph_adj (e.g. primitive or external type)
            # as long as it's a dependency. However, graph_adj should only contain nodes to be sorted.
            if dep in in_degree: # Only consider dependencies that are part of the sortable items
                 in_degree[node] +=1 
            elif dep not in PRIMITIVE_LUA_TYPES and dep != "fun(...)": # Warn about unknown types
                pass # Silently ignore unknown types for in_degree calculation, as they are external

    queue = deque([node for node, degree in in_degree.items() if degree == 0])
    sorted_order = []

    while queue:
        node = queue.popleft()
        sorted_order.append(node)

        for neighbor in sorted(list(adj_list_outgoing.get(node, set()))): 
            if neighbor in in_degree: # Ensure neighbor is part of the graph
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

    if len(sorted_order) == len(graph_adj):
        return sorted_order
    else:
        # Cycle detected or unreachable nodes
        processed_in_sorted = set(sorted_order)
        remaining_nodes = [node for node in graph_adj if node not in processed_in_sorted]
        remaining_nodes.sort() 
        
        # For debugging, identify nodes that still have positive in-degree
        cycle_participants = [node for node, degree in in_degree.items() if degree > 0 and node in remaining_nodes]
        
        print(f"Warning: Cycle detected in dependency graph or some nodes were unreachable. Nodes involved or dependent on cycles (or otherwise unsorted): {cycle_participants if cycle_participants else remaining_nodes}. Output order may not be optimal for these.", file=sys.stderr)
        return sorted_order + remaining_nodes


def export_to_lua(schema: Dict[str, Any], output_path: str) -> None:
    """
    Exports the given DCS schema to an EmmyLua annotation file,
    processing types in a topologically sorted order to ensure dependencies are met.

    :param schema: The loaded DCS API schema.
    :type schema: Dict[str, Any]
    :param output_path: The path where the .lua file will be saved.
    :type output_path: str
    """
    output_dir = os.path.dirname(output_path)
    if output_dir: 
        os.makedirs(output_dir, exist_ok=True)

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

    all_items: Dict[str, Tuple[Dict[str, Any], bool]] = {} 
    all_defined_type_names: Set[str] = set()

    for name, definition in schema.get("globals", {}).items():
        all_items[name] = (definition, True)
        all_defined_type_names.add(name)
    for name, definition in schema.get("types", {}).items():
        if name not in all_items: 
            all_items[name] = (definition, False)
        all_defined_type_names.add(name)
    
    dependency_graph: Dict[str, Set[str]] = {}
    for name, (item_def, _) in all_items.items():
        dependencies = get_item_dependencies(name, item_def, all_defined_type_names)
        dependency_graph[name] = dependencies

    
    sorted_item_names = topological_sort(dependency_graph)
    

    globals_processed_in_types_pass = set()

    output_content_parts.append("-- Global Namespaces and Classes")
    for name in sorted_item_names: 
        if name in schema.get("globals", {}):
            item_def, is_global = all_items[name]
            if is_global: 
                output_content_parts.append(process_class_like_definition(name, item_def, schema, True))
                globals_processed_in_types_pass.add(name)


    output_content_parts.append("\n-- Type Definitions (Enums, Aliases, Records/Classes)")
    for name in sorted_item_names: 
        if name in schema.get("types", {}):
            item_def, is_global = all_items[name]
            if not is_global: 
                if name not in processed_types: 
                    output_content_parts.append(process_type_definition(name, item_def, schema))
            elif name not in globals_processed_in_types_pass and name not in processed_types:
                output_content_parts.append(process_type_definition(name, item_def, schema))


    full_output_content = "\n".join(header_info + [part for part in output_content_parts if part and part.strip()])
    
    if not full_output_content.endswith("\n"):
        full_output_content += "\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_output_content)
    print(f"Lua type definitions exported to {output_path}")


def main():
    """
    Main function to parse arguments and initiate the export process.
    """
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
