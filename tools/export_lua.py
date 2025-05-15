#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, Set
import datetime # Added for timestamp

# LUA primitive type mapping
TYPE_MAPPING = {
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "table": "table",
    "function": "fun(...)", # EmmyLua convention for generic function
    "any": "any",
    "nil": "nil",
    "void": "nil", # Lua functions return nil by default if no return statement
}

# Track processed types to avoid re-defining ---@class annotations
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
    if " enum" in name: 
        name = name.replace(" enum", "")
    
    lua_keywords = {"end", "function", "if", "else", "then", "local", "and", "or", "not", "type", "repeat", "while", "for", "do", "return", "break", "goto", "in", "nil", "true", "false"}
    if name in lua_keywords:
        return f"_{name}"
    return name


def map_type(type_str: str) -> str:
    """Map DCS schema type to Lua type annotation"""
    if not type_str:
        return "any"
    if "|" in type_str:
        types = [map_type(t.strip()) for t in type_str.split("|")]
        return "|".join(types)
    if type_str.endswith("[]"):
        base_type = type_str[:-2].strip()
        return f"{map_type(base_type)}[]"
    if type_str.startswith("map<") and type_str.endswith(">"):
        inner_content = type_str[4:-1].strip()
        parts = inner_content.split(",", 1)
        if len(parts) == 2:
            key_type = map_type(parts[0].strip())
            value_type = map_type(parts[1].strip())
            return f"table<{key_type}, {value_type}>"
        else: 
            return f"table<any, {map_type(inner_content)}>"
    if type_str in TYPE_MAPPING:
        return TYPE_MAPPING[type_str]
    return type_str


def format_description(desc: str, indent: str = "") -> str:
    """Format description as a block of EmmyLua comments."""
    if not desc:
        return ""
    lines = desc.strip().split("\n")
    if not lines:
        return ""
    
    block_result = ""
    for line_content in lines:
        # Prepend "--- " to each line of the description block
        block_result += f"{indent}--- {line_content.strip()}\n" 
    return block_result

def format_multiline_annotation_desc(description: str) -> str:
    """Formats a multi-line description to be appended to an EmmyLua annotation.
       Ensures each line of the description is part of the EmmyLua comment.
       Example: ---@field name type Main description line
       --- Additional line 1
       --- Additional line 2
    """
    if not description:
        return ""
    
    lines = description.strip().split('\n')
    if not lines:
        return ""

    # First line is appended directly (with a leading space)
    formatted = " " + lines[0].strip()
    
    # Subsequent lines start with "--- "
    if len(lines) > 1:
        for i in range(1, len(lines)):
            stripped_line = lines[i].strip()
            if stripped_line: # Only add if the line has content
                formatted += f"\n--- {stripped_line}" 
    return formatted


def process_param(param: Dict[str, Any]) -> str:
    """Process a parameter into an EmmyLua @param annotation"""
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


def process_enum(name: str, enum_def: Dict[str, Any]) -> str:
    """Process an enum into Lua annotation and table definition.
       Relies on the caller (process_type_definition) to have handled `processed_types`.
    """
    values = enum_def.get("values", {}) 
    desc = enum_def.get("description", "")

    result = format_description(desc) # Use new format_description for block
    result += f"---@enum {name}\n"
    
    lua_assignment_code = ""
    if "." in name:
        path_parts = name.split('.')
        for i in range(len(path_parts) - 1): 
            intermediate_table_to_ensure = ".".join(path_parts[:i+1]) 
            next_part = path_parts[i+1] 
            full_intermediate_path = f"{intermediate_table_to_ensure}.{next_part}"

            if full_intermediate_path not in initialized_lua_tables and full_intermediate_path != name:
                lua_assignment_code += f"{full_intermediate_path} = {intermediate_table_to_ensure}.{next_part} or {{}}\n"
                initialized_lua_tables.add(full_intermediate_path)

    result += f"{lua_assignment_code}{name} = {{\n"

    if isinstance(values, list): 
        for i, val_str in enumerate(values):
            clean_key = sanitize_lua_name(val_str) 
            if any(c in val_str for c in " -+/.") or val_str.isdigit() or clean_key != val_str :
                 result += f'    ["{val_str}"] = "{val_str}"' 
            else:
                result += f'    {clean_key} = "{val_str}"'
            if i < len(values) - 1:
                result += ","
            result += "\n"
    elif isinstance(values, dict):
        items = list(values.items())
        for i, (key, value) in enumerate(items):
            if not key: continue 

            lua_key_str = key
            # Check if key needs to be quoted for Lua table assignment
            if not isinstance(key, (int, float)) and (not isinstance(key, str) or not key.isidentifier() or any(c in key for c in " -+/.")):
                 lua_key_str = f'["{key}"]'
            elif isinstance(key, (int, float)): # Numeric keys use brackets
                 lua_key_str = f'[{key}]'
            
            if isinstance(value, str):
                formatted_value = f'"{value}"'
            elif isinstance(value, (int, float)):
                formatted_value = str(value)
            else: 
                formatted_value = f'"{key}"' # Fallback, or could be error/specific handling

            result += f"    {lua_key_str} = {formatted_value}"
            if i < len(items) - 1:
                result += ","
            result += "\n"

    if not values: 
        result += "    -- _EMPTY_ENUM_ = true -- Placeholder for empty enum\n"

    result += "}\n" # Corrected: Only one closing brace for the enum table itself
    initialized_lua_tables.add(name) # Mark the Lua table for this enum as initialized
    return result


def process_type_definition(name: str, type_def: Dict[str, Any], schema: Dict[str, Any]) -> str:
    """Process a type (class/record/enum) into Lua class definition and table assignment"""
    if name in processed_types: 
        return ""
    processed_types.add(name) # Add to processed_types here, once.

    kind = type_def.get("kind", "record") 

    if kind == "enum":
        # process_enum no longer checks/adds to processed_types itself.
        return process_enum(name, type_def) 
    
    # For 'record' or 'class' types
    desc = type_def.get("description", "")
    inherits = type_def.get("inherits", []) 
    if isinstance(inherits, str) and inherits:
        inherits = [inherits]
    
    class_annotation_block = format_description(desc) 
    class_annotation_block += f"---@class {name}"
    if inherits:
        class_annotation_block += f" : {', '.join(map_type(inh) for inh in inherits)}"
    class_annotation_block += "\n"

    properties = type_def.get("properties", {})
    if not properties and "fields" in type_def: 
        properties = type_def.get("fields", {})
        
    static_props = type_def.get("static", {}) 
    all_fields_for_annotation = {**properties} 

    for prop_name, prop_def in all_fields_for_annotation.items():
        prop_type_val = prop_def.get("type", "any")
        prop_desc = prop_def.get("description", "")
        prop_optional = prop_def.get("optional", False)
        
        lua_prop_name = sanitize_lua_name(prop_name)
        if prop_optional:
            lua_prop_name += "?"

        if isinstance(prop_type_val, list):
            type_str = "|".join(map_type(t) for t in prop_type_val if isinstance(t, str)) or "any"
        else:
            type_str = map_type(prop_type_val)

        field_line = f"---@field {lua_prop_name} {type_str}"
        if prop_desc:
            field_line += format_multiline_annotation_desc(prop_desc) 
        class_annotation_block += field_line + "\n"
            
    lua_assignment_code = ""
    if "." in name: 
        path_parts = name.split('.')
        for i in range(len(path_parts) - 1): 
            intermediate_table_to_ensure = ".".join(path_parts[:i+1]) 
            next_part = path_parts[i+1] 
            full_intermediate_path = f"{intermediate_table_to_ensure}.{next_part}" 

            if full_intermediate_path not in initialized_lua_tables and full_intermediate_path != name: 
                lua_assignment_code += f"{full_intermediate_path} = {intermediate_table_to_ensure}.{next_part} or {{}}\n"
                initialized_lua_tables.add(full_intermediate_path)
    
    if name not in initialized_lua_tables:
        lua_assignment_code += f"{name} = {{}}\n"
        initialized_lua_tables.add(name)
    else: 
        lua_assignment_code += f"-- {name} table already initialized or is a namespace parent.\n"

    # Static properties are added as fields to the class annotation block
    if static_props:
        for static_prop_name, static_prop_def in static_props.items():
            static_type = map_type(static_prop_def.get("type", "any"))
            static_desc = static_prop_def.get("description", "")
            
            static_field_line = f"---@field {sanitize_lua_name(static_prop_name)} {static_type}"
            if static_desc:
                 static_field_line += format_multiline_annotation_desc(static_desc) 
            class_annotation_block += static_field_line + "\n"
            # Note: Actual Lua assignment for static fields (e.g., MyClass.CONST = 10)
            # would need values from schema or be handled manually. This script focuses on annotations.
    
    method_definitions = ""
    instance_methods = type_def.get("instance", {})
    if not instance_methods and "methods" in type_def: 
        instance_methods = type_def.get("methods", {})

    for method_name, method_def_list in instance_methods.items():
        current_method_def = method_def_list
        if isinstance(method_def_list, list):
            if not method_def_list: continue
            current_method_def = method_def_list[0] 
        method_definitions += process_method(name, method_name, current_method_def)

    return f"{class_annotation_block}{lua_assignment_code}\n{method_definitions}"


def process_method(class_name: str, method_name: str, method_def: Dict[str, Any]) -> str:
    """Process a method into Lua function definition with EmmyLua annotations"""
    params_list = method_def.get("params", [])
    returns_list = method_def.get("returns", []) 
    desc = method_def.get("description", "")

    result = format_description(desc) 

    for param_def in params_list:
        result += process_param(param_def) + "\n"

    if isinstance(returns_list, str): 
        if returns_list and returns_list.lower() != "void" and returns_list.lower() != "nil":
            return_line = f"---@return {map_type(returns_list)}"
            # Consider adding description if schema provides it for single string return
            # ret_desc = method_def.get("return_description", "") # Example if schema had it
            # if ret_desc: return_line += format_multiline_annotation_desc(ret_desc)
            result += return_line + "\n"
    elif isinstance(returns_list, list):
        if not returns_list or (len(returns_list) == 1 and isinstance(returns_list[0], str) and (returns_list[0].lower() == "void" or returns_list[0].lower() == "nil")):
             pass # No return or explicit single void/nil
        else:
            for i, ret_type_def in enumerate(returns_list):
                ret_type_str = "any"
                ret_desc = ""
                if isinstance(ret_type_def, str): 
                    ret_type_str = map_type(ret_type_def)
                    # If schema provides description for list items differently, adjust here
                elif isinstance(ret_type_def, dict): 
                    ret_type_str = map_type(ret_type_def.get("type", "any"))
                    ret_desc = ret_type_def.get("description", "")

                # Skip if it's a void/nil type unless it's the only return (already handled by outer if)
                if ret_type_str.lower() == "void" or ret_type_str.lower() == "nil": 
                    if len(returns_list) == 1 and i == 0 : continue # Already handled if single void
                    # If part of multiple returns, EmmyLua might expect 'nil' explicitly
                    # For now, we'll output it as 'nil' if it's not the sole 'void'
                    ret_type_str = "nil"


                return_line = f"---@return {ret_type_str}"
                if ret_desc:
                    return_line += format_multiline_annotation_desc(ret_desc) 
                result += return_line + "\n"
    
    sanitized_params = [sanitize_lua_name(p.get("name", f"arg{i+1}")) for i, p in enumerate(params_list)]
    lua_method_name = sanitize_lua_name(method_name) 
    if lua_method_name != method_name and (not hasattr(method_name, 'isidentifier') or not method_name.isidentifier()):
        lua_method_name = f'["{method_name}"]'

    result += f"function {class_name}:{lua_method_name}({', '.join(sanitized_params)}) end\n\n"
    return result


def process_global(name: str, global_def: Dict[str, Any], schema: Dict[str, Any]) -> str:
    """Process a global (singleton or class-like global table)"""
    if name in processed_types: 
        # This ensures we don't redefine the ---@class and its direct fields/methods
        # if the global name somehow matched a type name processed earlier.
        # However, Lua assignment might still be needed if not yet done.
        if name not in initialized_lua_tables:
            # This case should be rare if globals are processed first and uniquely named.
            # Ensures the global table is at least initialized.
            return f"{name} = {{}} -- Global table (re-init check)\n" 
        return "" # Already fully processed
    
    desc = global_def.get("description", "")
    
    class_annotation_block = format_description(desc) 
    class_annotation_block += f"---@class {name}\n"

    properties = global_def.get("properties", {}) # Instance-like properties on the global table
    static_fields_on_global = global_def.get("static", {}) # Functions or sub-tables directly on the global
    
    # Fields for ---@class annotation: combines 'properties' and 'static' as they all live on the global table
    all_fields_for_annotation = {**properties, **static_fields_on_global}

    for prop_name, prop_def in all_fields_for_annotation.items():
        prop_type_val = prop_def.get("type", "any")
        prop_desc = prop_def.get("description", "")
        prop_optional = prop_def.get("optional", False) # Though less common for global fields

        lua_prop_name = sanitize_lua_name(prop_name)
        if prop_optional: # Optionality for fields
            lua_prop_name += "?"
        
        if isinstance(prop_type_val, list): # Union type
            type_str = "|".join(map_type(t) for t in prop_type_val if isinstance(t, str)) or "any"
        else:
            type_str = map_type(prop_type_val)
        
        field_line = f"---@field {lua_prop_name} {type_str}"
        if prop_desc:
            field_line += format_multiline_annotation_desc(prop_desc) 
        class_annotation_block += field_line + "\n"

    lua_assignment_code = ""
    if name not in initialized_lua_tables:
        lua_assignment_code += f"{name} = {{}}\n"
        initialized_lua_tables.add(name)
    else:
        # This might happen if a namespace type like "A.B" was created, and "A" is also a global.
        lua_assignment_code += f"-- {name} global table likely already initialized as a namespace parent.\n"

    method_definitions = ""
    # Globals can have "static" functions which are effectively methods on the global table itself.
    # Or "instance" methods if the global itself is treated as a class instance.
    # The schema uses "static" for functions directly on globals like `coord.LLtoLO`.
    # And "instance" for globals that are classes like `Controller`.
    
    # Let's treat "static" in globals as methods if their type is 'function' or params exist
    # This is a common pattern for global utility tables.
    global_methods = {}
    if "static" in global_def:
        for member_name, member_def in global_def["static"].items():
            # Heuristic: if it has 'params' or 'returns', it's likely a function.
            # Or if its 'type' is 'function' (though your schema uses 'any' for fields that are functions)
            if "params" in member_def or "returns" in member_def:
                 global_methods[member_name] = member_def

    # Also consider 'instance' methods if the global is class-like
    if "instance" in global_def:
        global_methods.update(global_def["instance"])
    if "methods" in global_def and not global_methods: # Fallback
        global_methods.update(global_def["methods"])


    for method_name, method_def_list in global_methods.items():
        current_method_def = method_def_list
        if isinstance(method_def_list, list): 
            if not method_def_list: continue
            current_method_def = method_def_list[0] # Take first overload
        
        # For globals, methods are usually defined with '.' (e.g., global.method())
        # unless the global itself is being treated as an instantiable class.
        # Your schema for `Controller` (a global class) uses `instance` methods, so `Controller:method()` is correct.
        # For `coord` (a global singleton with static functions), `coord.LLtoLO()` is the access pattern.
        # EmmyLua handles `---@field func_name fun()` for table functions, or `function table.func_name()`
        
        # If 'params' or 'returns' are present, it's a function.
        # The `process_method` generates `function class_name:method_name()`.
        # For global singletons with functions, we want `function global_name.method_name()`.
        # This requires a slight adjustment or a different processing path.

        # For now, let's assume `process_method` is for class-style methods (`:`).
        # If a global has "static" functions, they are documented as fields of type `fun(...)`
        # and their actual Lua definition would be `function Global.FuncName() end`.
        # The current `---@field func_name any ...` from `all_fields_for_annotation`
        # might need to be `---@field func_name fun(param:type):return_type` for better EmmyLua.

        # If the global_def has "instance" methods, it's treated like a class.
        if "instance" in global_def or (global_def.get("kind") == "class" and "methods" in global_def):
             method_definitions += process_method(name, method_name, current_method_def)
        # else:
            # For static functions on a global table, they are already covered by ---@field if type is 'function'
            # or if we enhance field processing to detect functions.
            # To generate full function signatures for static global functions:
            # method_definitions += process_static_function_on_global(name, method_name, current_method_def)
            # This would be a new helper similar to process_method but using `.`

    processed_types.add(name) # Mark the class annotation for this global as done.
    return f"{class_annotation_block}{lua_assignment_code}\n{method_definitions}"


def export_to_lua(schema: Dict[str, Any], output_path: str) -> None:
    """Export schema to Lua EmmyLua annotations"""
    output_dir = os.path.dirname(output_path)
    if output_dir: 
        os.makedirs(output_dir, exist_ok=True)

    output_content = [
        "--[[ DCS World Lua Type Definitions",
        f"Generated from schema: {os.path.basename(schema.get('source_file_path', 'unknown_schema.json')) if 'source_file_path' in schema else ''}",
        "DO NOT MODIFY - AUTO-GENERATED FILE",
        f"Generated on: {datetime.datetime.now().isoformat()}", 
        "--]]",
        "",
        "---@meta",
        "",
    ]
    
    processed_types.clear()
    initialized_lua_tables.clear()

    # 1. Process Globals first
    if "globals" in schema:
        output_content.append("-- Global Namespaces and Classes")
        for global_name, global_def in sorted(schema["globals"].items()):
            output_content.append(process_global(global_name, global_def, schema))

    # 2. Process Standalone Types (no dots, not already processed as a global's class)
    if "types" in schema:
        output_content.append("\n-- Standalone Type Definitions")
        for type_name, type_def in sorted(schema["types"].items()):
            if "." not in type_name and type_name not in processed_types: 
                output_content.append(process_type_definition(type_name, type_def, schema))
    
    # 3. Process Namespaced Types (with dots, not already processed as a global's class)
    if "types" in schema:
        output_content.append("\n-- Namespaced Type Definitions")
        for type_name, type_def in sorted(schema["types"].items()):
            if "." in type_name and type_name not in processed_types: 
                output_content.append(process_type_definition(type_name, type_def, schema))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_content))

    print(f"Lua type definitions exported to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Export DCS schema to Lua EmmyLua annotations"
    )
    parser.add_argument("schema_file", help="Path to the DCS schema JSON file")
    parser.add_argument(
        "--output",
        "-o",
        default="dist/dcs-world-api.lua",
        help="Output Lua definition file (default: dist/dcs-world-api.lua)",
    )

    args = parser.parse_args()

    try:
        schema_data = load_schema(args.schema_file)
        schema_data['source_file_path'] = args.schema_file # For header info
        export_to_lua(schema_data, args.output)
    except Exception as e:
        print(f"Error processing schema {args.schema_file}: {e}", file=sys.stderr)
        import traceback 
        traceback.print_exc() 
        sys.exit(1)


if __name__ == "__main__":
    main()
