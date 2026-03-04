"""MCP server with 10 tools for UE Material graph intelligence."""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import logging
from pathlib import PurePosixPath

from mcp.server.fastmcp import FastMCP

from unreal_material_mcp.config import UE_PROJECT_PATH
from unreal_material_mcp.editor_bridge import EditorBridge, EditorNotRunning

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "unreal-material",
    instructions=(
        "Provides intelligence and editing tools for Unreal Engine material graphs. "
        "Use these tools to inspect material properties, parameters, node graphs, "
        "search for materials, analyze performance, compare materials, "
        "edit material instances, and modify material graphs in an Unreal project."
    ),
)

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_bridge: EditorBridge | None = None
_project_path: str = UE_PROJECT_PATH
_helper_uploaded: bool = False
_helper_hash: str = ""


def _reset_state() -> None:
    """Reset module singletons (used by tests)."""
    global _bridge, _helper_uploaded, _helper_hash, _project_path
    _bridge = None
    _helper_uploaded = False
    _helper_hash = ""
    _project_path = UE_PROJECT_PATH


def _get_bridge() -> EditorBridge:
    """Return (and lazily create) the editor bridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = EditorBridge(auto_connect=False)
    return _bridge


def _get_helper_source() -> str:
    """Read the helpers/material_helpers.py source from the installed package."""
    ref = importlib.resources.files("unreal_material_mcp") / "helpers" / "material_helpers.py"
    return ref.read_text(encoding="utf-8")


def _escape_py_string(s: str) -> str:
    """Escape a string for safe embedding inside a Python triple-quoted string."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


def _ensure_helper_uploaded() -> None:
    """Upload the helper module to {project}/Saved/MaterialMCP/ if needed."""
    global _helper_uploaded, _helper_hash

    if _helper_uploaded:
        return

    source = _get_helper_source()
    new_hash = hashlib.md5(source.encode("utf-8")).hexdigest()

    if new_hash == _helper_hash:
        _helper_uploaded = True
        return

    # Build a script that writes the helper file inside the editor
    saved_dir = _project_path.replace("\\", "/") + "/Saved/MaterialMCP"
    escaped_source = _escape_py_string(source)

    upload_script = (
        "import os\n"
        f"d = '{saved_dir}'\n"
        "os.makedirs(d, exist_ok=True)\n"
        f"p = os.path.join(d, 'material_helpers.py')\n"
        f'f = open(p, "w", encoding="utf-8")\n'
        f'f.write(\'\'\'{escaped_source}\'\'\')\n'
        "f.close()\n"
        "print('helper_uploaded')\n"
    )

    bridge = _get_bridge()
    bridge.run_command(upload_script)

    _helper_hash = new_hash
    _helper_uploaded = True


def _run_material_script(script_body: str) -> dict:
    """Upload helper (if needed), run *script_body* in the editor, parse JSON output.

    The *script_body* must end with a ``print(json.dumps(...))`` call so that
    the output contains exactly one JSON object.
    """
    _ensure_helper_uploaded()

    saved_dir = _project_path.replace("\\", "/") + "/Saved/MaterialMCP"

    preamble = (
        "import sys, json\n"
        f"sys.path.insert(0, '{saved_dir}')\n"
        "import importlib, material_helpers\n"
        "importlib.reload(material_helpers)\n"
    )

    full_script = preamble + script_body
    bridge = _get_bridge()
    result = bridge.run_command(full_script)

    # The bridge returns a dict with 'output' or 'result' containing printed text.
    output = result.get("output", "") or result.get("result", "") or ""

    # Handle list output — UE remote execution returns [{'type': 'Info', 'output': '...'}]
    if isinstance(output, list):
        parts = []
        for item in output:
            if isinstance(item, dict):
                parts.append(item.get("output", str(item)))
            else:
                parts.append(str(item))
        output = "\n".join(parts)

    output = str(output).strip()

    # Find the JSON object in the output
    json_start = output.find("{")
    if json_start == -1:
        return {"success": False, "error": f"No JSON in output: {output[:200]}"}

    try:
        return json.loads(output[json_start:])
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Invalid JSON: {exc} — raw: {output[:200]}"}


def _format_error(data: dict) -> str | None:
    """If *data* indicates an error, return the message; otherwise ``None``."""
    if data.get("success") is False:
        return data.get("error", "Unknown error")
    return None


# ---------------------------------------------------------------------------
# Tool 1: get_material_info
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_info(asset_path: str) -> str:
    """Get core metadata for a material or material instance.

    Returns blend mode, shading model, domain, two-sided flag, expression
    count, and usage flags.

    Args:
        asset_path: Unreal asset path, e.g. '/Game/Materials/M_Foo'
    """
    script = (
        f"result = material_helpers.get_material_info('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Material: {data.get('asset_path', asset_path)}",
        f"  Type: {data.get('asset_type', 'Unknown')}",
    ]

    if data.get("asset_type") == "MaterialInstanceConstant":
        lines.append(f"  Parent: {data.get('parent', 'N/A')}")
    else:
        lines.append(f"  Blend Mode: {data.get('blend_mode', 'N/A')}")
        lines.append(f"  Shading Model: {data.get('shading_model', 'N/A')}")
        lines.append(f"  Domain: {data.get('material_domain', 'N/A')}")
        lines.append(f"  Two Sided: {data.get('two_sided', False)}")
        lines.append(f"  Expressions: {data.get('expression_count', 'N/A')}")

        usage = data.get("usage_flags", {})
        if usage:
            enabled = [k for k, v in usage.items() if v]
            if enabled:
                lines.append(f"  Usage Flags: {', '.join(enabled)}")
            else:
                lines.append("  Usage Flags: (none)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 2: get_material_parameters
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_parameters(asset_path: str) -> str:
    """List all parameters (scalar, vector, texture, static switch) in a material.

    Args:
        asset_path: Unreal asset path, e.g. '/Game/Materials/M_Foo'
    """
    script = (
        f"result = material_helpers.get_all_parameters('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    params = data.get("parameters", [])
    if not params:
        return f"Material: {data.get('asset_path', asset_path)}\n  No parameters found."

    # Group by type
    groups: dict[str, list] = {}
    for p in params:
        ptype = p.get("type", "Unknown")
        groups.setdefault(ptype, []).append(p)

    lines = [f"Material: {data.get('asset_path', asset_path)}"]
    lines.append(f"  Total parameters: {len(params)}")

    for ptype in ("Scalar", "Vector", "Texture", "StaticSwitch"):
        items = groups.get(ptype, [])
        if not items:
            continue
        lines.append(f"  [{ptype}] ({len(items)})")
        for p in items:
            default = p.get("default")
            if isinstance(default, dict):
                # Vector: show r/g/b/a
                parts = [f"{k}={v}" for k, v in default.items()]
                default_str = f"({', '.join(parts)})"
            elif default is None:
                default_str = "(none)"
            else:
                default_str = str(default)

            # Static switch: show value= instead of = for clarity
            if ptype == "StaticSwitch":
                lines.append(f"    {p['name']} value={default_str}")
                for ctrl in p.get("controls", []):
                    true_in = ctrl.get("true_input", "?")
                    false_in = ctrl.get("false_input", "?")
                    lines.append(
                        f"      Controls: {ctrl.get('expression', '?')} "
                        f"(true→{true_in}, false→{false_in})"
                    )
            else:
                lines.append(f"    {p['name']} = {default_str}")

    # Any remaining types
    for ptype, items in groups.items():
        if ptype in ("Scalar", "Vector", "Texture", "StaticSwitch"):
            continue
        lines.append(f"  [{ptype}] ({len(items)})")
        for p in items:
            lines.append(f"    {p['name']} = {p.get('default', '(none)')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 3: get_material_expressions
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_expressions(asset_path: str, class_filter: str | None = None) -> str:
    """Scan all expression nodes in a material graph.

    Args:
        asset_path: Unreal asset path, e.g. '/Game/Materials/M_Foo'
        class_filter: Optional expression class name to filter (e.g. 'Add', 'TextureSample')
    """
    filter_arg = f"'{_escape_py_string(class_filter)}'" if class_filter else "None"
    script = (
        f"result = material_helpers.scan_all_expressions("
        f"'{_escape_py_string(asset_path)}', class_filter={filter_arg})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    expected = data.get("expected_expression_count", -1)
    found = data.get("found_expression_count", 0)
    expressions = data.get("expressions", [])

    lines = [
        f"Material: {data.get('asset_path', asset_path)}",
        f"  Expressions: {found} found / {expected} expected",
    ]

    # Group by class
    groups: dict[str, list] = {}
    for expr in expressions:
        cls = expr.get("class", "Unknown")
        groups.setdefault(cls, []).append(expr)

    for cls in sorted(groups.keys()):
        items = groups[cls]
        lines.append(f"  [{cls}] ({len(items)})")
        for expr in items:
            pos = expr.get("position", {})
            pos_str = f"({pos.get('x', 0)}, {pos.get('y', 0)})"
            name = expr.get("name", "?")
            parts = [f"{name} @ {pos_str}"]

            # Show key properties
            if "parameter_name" in expr:
                parts.append(f"param={expr['parameter_name']}")
            if "value" in expr:
                parts.append(f"value={expr['value']}")
            if "texture" in expr:
                parts.append(f"texture={expr['texture']}")
            if "function" in expr:
                parts.append(f"function={expr['function']}")
            if "code" in expr:
                code_preview = expr["code"][:60]
                parts.append(f"code={code_preview!r}")
            if "text" in expr:
                parts.append(f"text={expr['text']!r}")

            lines.append(f"    {' | '.join(parts)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 4: trace_material_connections
# ---------------------------------------------------------------------------

def _format_tree(node: dict, indent: int = 0) -> list[str]:
    """Recursively format a connection tree into indented lines."""
    prefix = "  " * indent
    name = node.get("name", "?")
    pos = node.get("position", {})
    pos_str = f"({pos.get('x', 0)}, {pos.get('y', 0)})"

    lines = [f"{prefix}{name} @ {pos_str}"]

    if node.get("cycle"):
        lines[-1] += " [CYCLE]"
        return lines
    if node.get("truncated"):
        lines[-1] += " [TRUNCATED]"
        return lines

    for inp in node.get("inputs", []):
        in_name = inp.get("input_name", "?")
        child = inp.get("connected_node", {})
        lines.append(f"{prefix}  <- {in_name}:")
        lines.extend(_format_tree(child, indent + 2))

    return lines


@mcp.tool()
def trace_material_connections(asset_path: str, expression_name: str | None = None) -> str:
    """Trace the connection graph of a material.

    If expression_name is given, traces inputs of that specific node.
    Otherwise traces from all connected material output pins.

    Args:
        asset_path: Unreal asset path, e.g. '/Game/Materials/M_Foo'
        expression_name: Optional expression name (e.g. 'MaterialExpressionAdd_0')
    """
    if expression_name:
        expr_arg = f"'{_escape_py_string(expression_name)}'"
    else:
        expr_arg = "None"

    script = (
        f"result = material_helpers.trace_connections("
        f"'{_escape_py_string(asset_path)}', expression_name={expr_arg})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [f"Material: {data.get('asset_path', asset_path)}"]

    if "tree" in data:
        lines.append("Connection tree:")
        lines.extend(_format_tree(data["tree"], indent=1))
    elif "output_pins" in data:
        pins = data["output_pins"]
        if not pins:
            lines.append("  No connected output pins.")
        else:
            for pin_name, tree in pins.items():
                lines.append(f"  [{pin_name}]")
                lines.extend(_format_tree(tree, indent=2))
    else:
        lines.append("  No connection data returned.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 5: search_materials
# ---------------------------------------------------------------------------

@mcp.tool()
def search_materials(
    base_path: str,
    query: str = "",
    filter_type: str = "name",
) -> str:
    """Search for materials and material instances under a content path.

    Args:
        base_path: Content browser path, e.g. '/Game/Materials'
        query: Search string (interpretation depends on filter_type)
        filter_type: One of 'name', 'parameter', 'expression', 'shading_model'
    """
    script = (
        f"result = material_helpers.search_materials_in_path("
        f"'{_escape_py_string(base_path)}', "
        f"query='{_escape_py_string(query)}', "
        f"filter_type='{_escape_py_string(filter_type)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    results = data.get("results", [])
    count = data.get("count", len(results))

    lines = [
        f"Search: base_path={data.get('base_path', base_path)}"
        f"  filter={data.get('filter_type', filter_type)}"
        f"  query={data.get('query', query)!r}",
        f"  Found: {count} material(s)",
    ]

    for r in results:
        cls = r.get("class", "Material")
        path = r.get("asset_path", "?")
        name = r.get("asset_name", "?")
        line = f"    {name} ({cls}) — {path}"
        if "shading_model" in r:
            line += f" [shading_model={r['shading_model']}]"
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 6: get_material_stats
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_stats(asset_path: str) -> str:
    """Get shader compilation statistics and performance warnings for a material.

    Returns shader instruction counts, sampler usage, texture samples,
    UV scalars, interpolator scalars, and any performance warnings.

    Args:
        asset_path: Unreal asset path, e.g. '/Game/Materials/M_Foo'
    """
    script = (
        f"result = material_helpers.get_stats('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    stats = data.get("stats", {})
    lines = [
        f"Material: {data.get('asset_path', asset_path)}",
        f"  Shader Instructions: VS={stats.get('num_vertex_shader_instructions', 'N/A')} PS={stats.get('num_pixel_shader_instructions', 'N/A')}",
        f"  Samplers: {stats.get('num_samplers', 'N/A')}",
        f"  Texture Samples: pixel={stats.get('num_pixel_texture_samples', 'N/A')} vertex={stats.get('num_vertex_texture_samples', 'N/A')} VT={stats.get('num_virtual_texture_samples', 'N/A')}",
        f"  UV Scalars: {stats.get('num_uv_scalars', 'N/A')}",
        f"  Interpolator Scalars: {stats.get('num_interpolator_scalars', 'N/A')}",
    ]

    compile_status = data.get("compile_status")
    if compile_status:
        lines.append(f"  Compile Status: {compile_status}")
    compile_errors = data.get("compile_errors", [])
    if compile_errors:
        lines.append("  Compile Errors:")
        for e in compile_errors:
            lines.append(f"    - {e}")

    warnings = data.get("warnings", [])
    if warnings:
        lines.append("  Warnings:")
        for w in warnings:
            lines.append(f"    - {w}")
    else:
        lines.append("  No warnings.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 7: get_material_dependencies
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_dependencies(asset_path: str) -> str:
    """List textures, material functions, and parameter sources used by a material.

    Args:
        asset_path: Unreal asset path, e.g. '/Game/Materials/M_Foo'
    """
    script = (
        f"result = material_helpers.get_dependencies('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [f"Material: {data.get('asset_path', asset_path)}"]

    textures = data.get("textures", [])
    lines.append(f"  Textures ({len(textures)}):")
    if textures:
        for t in textures:
            if isinstance(t, dict):
                path = t.get("path", "?")
                w = t.get("width")
                h = t.get("height")
                fmt = t.get("format")
                size_str = f" ({w}x{h}, {fmt})" if w and h and fmt else ""
                lines.append(f"    {path}{size_str}")
            else:
                lines.append(f"    {t}")
    else:
        lines.append("    (none)")

    functions = data.get("functions", [])
    lines.append(f"  Material Functions ({len(functions)}):")
    if functions:
        for f in functions:
            expr = f.get("expression", "?")
            fpath = f.get("function_path", "?")
            lines.append(f"    {expr} -> {fpath}")
    else:
        lines.append("    (none)")

    sources = data.get("parameter_sources", [])
    lines.append(f"  Parameter Sources ({len(sources)}):")
    if sources:
        for s in sources:
            lines.append(f"    {s}")
    else:
        lines.append("    (none)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 8: inspect_material_function
# ---------------------------------------------------------------------------

@mcp.tool()
def inspect_material_function(asset_path: str, function_name: str | None = None) -> str:
    """Inspect a material function asset or a function call within a material.

    If function_name is given, looks up that specific function call expression.
    Otherwise inspects the material function asset directly.

    Args:
        asset_path: Unreal asset path, e.g. '/Game/Functions/MF_Foo'
        function_name: Optional function expression name within a material
    """
    if function_name:
        fn_arg = f"'{_escape_py_string(function_name)}'"
    else:
        fn_arg = "None"

    script = (
        f"result = material_helpers.inspect_function("
        f"'{_escape_py_string(asset_path)}', function_name={fn_arg})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Function: {data.get('function_path', asset_path)}",
        f"  Description: {data.get('description', '(none)')}",
        f"  Caption: {data.get('caption', '(none)')}",
        f"  Expression Count: {data.get('expression_count', 'N/A')}",
    ]

    inputs = data.get("inputs", [])
    lines.append(f"  Inputs ({len(inputs)}):")
    for inp in inputs:
        lines.append(f"    {inp.get('name', '?')} ({inp.get('type', '?')})")

    outputs = data.get("outputs", [])
    lines.append(f"  Outputs ({len(outputs)}):")
    for out in outputs:
        lines.append(f"    {out.get('name', '?')} ({out.get('type', '?')})")

    # Expression graph grouped by class (excluding FunctionInput/FunctionOutput)
    expressions = data.get("expressions", [])
    groups: dict[str, list] = {}
    for expr in expressions:
        cls = expr.get("class", "Unknown")
        if cls in ("FunctionInput", "FunctionOutput"):
            continue
        groups.setdefault(cls, []).append(expr)

    if groups:
        lines.append("  Expressions:")
        for cls in sorted(groups.keys()):
            items = groups[cls]
            lines.append(f"    [{cls}] ({len(items)})")
            for expr in items:
                lines.append(f"      {expr.get('name', '?')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 9: get_material_instance_chain
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_instance_chain(asset_path: str) -> str:
    """Walk the parent chain of a material instance up to the root material.

    Shows parameter overrides at each level and lists child instances.

    Args:
        asset_path: Unreal asset path, e.g. '/Game/Materials/MI_Foo'
    """
    script = (
        f"result = material_helpers.get_instance_chain('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    chain = data.get("chain", [])
    lines = [f"Instance Chain: {data.get('asset_path', asset_path)}"]

    for i, level in enumerate(chain):
        indent = "  " * (i + 1)
        path = level.get("asset_path", "?")
        asset_type = level.get("asset_type", "?")
        lines.append(f"  [{i}] {path} ({asset_type})")

        if asset_type == "MaterialInstanceConstant":
            overrides = level.get("overrides", [])
            if overrides:
                display_limit = 20
                for ov in overrides[:display_limit]:
                    lines.append(f"{indent}  {ov.get('name', '?')} = {ov.get('value', '?')}")
                if len(overrides) > display_limit:
                    lines.append(f"{indent}  ... and {len(overrides) - display_limit} more")
        else:
            # Root material
            if "blend_mode" in level:
                lines.append(f"{indent}  Blend Mode: {level['blend_mode']}")
            if "shading_model" in level:
                lines.append(f"{indent}  Shading Model: {level['shading_model']}")

    children = data.get("children", [])
    if children:
        lines.append(f"  Children ({len(children)}):")
        for c in children:
            lines.append(f"    {c}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 10: compare_materials
# ---------------------------------------------------------------------------

@mcp.tool()
def compare_materials(asset_path_a: str, asset_path_b: str) -> str:
    """Compare two materials side-by-side.

    Shows parameters only in A, only in B, and changed between them,
    plus differences in properties, stats, and expression counts.

    Args:
        asset_path_a: Unreal asset path for the first material
        asset_path_b: Unreal asset path for the second material
    """
    script = (
        f"result = material_helpers.compare_materials("
        f"'{_escape_py_string(asset_path_a)}', '{_escape_py_string(asset_path_b)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Compare: {data.get('path_a', asset_path_a)}",
        f"     vs: {data.get('path_b', asset_path_b)}",
    ]

    only_a = data.get("only_a", [])
    only_b = data.get("only_b", [])
    changed = data.get("changed", [])

    if only_a or only_b or changed:
        lines.append("  Parameters:")
        for name in only_a:
            lines.append(f"    - {name}")
        for name in only_b:
            lines.append(f"    + {name}")
        for name in changed:
            lines.append(f"    ~ {name}")
    else:
        lines.append("  Parameters: identical")

    prop_diff = data.get("property_diff", {})
    if prop_diff:
        lines.append("  Property Differences:")
        for key, vals in prop_diff.items():
            lines.append(f"    {key}: {vals.get('a', 'N/A')} -> {vals.get('b', 'N/A')}")

    stats_diff = data.get("stats_diff", {})
    if stats_diff:
        lines.append("  Stats Differences:")
        for key, vals in stats_diff.items():
            lines.append(f"    {key}: {vals.get('a', 'N/A')} -> {vals.get('b', 'N/A')}")

    expr_diff = data.get("expression_diff", {})
    if expr_diff:
        lines.append("  Expression Differences:")
        for key, vals in expr_diff.items():
            lines.append(f"    {key}: {vals.get('a', 0)} -> {vals.get('b', 0)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 11: set_material_instance_parameter
# ---------------------------------------------------------------------------

@mcp.tool()
def set_material_instance_parameter(
    asset_path: str,
    parameter_name: str,
    value: str,
    parameter_type: str | None = None,
) -> str:
    """Set a parameter override on a material instance.

    Args:
        asset_path: Unreal asset path to a MaterialInstanceConstant
        parameter_name: Name of the parameter to set
        value: New value as a string (number, boolean, JSON dict for vectors)
        parameter_type: Optional type hint ('Scalar', 'Vector', 'Texture', 'StaticSwitch')
    """
    # Parse value: try JSON first (handles vectors like {"r":1,"g":0,"b":0,"a":1}), fall back to raw string
    try:
        parsed_value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        parsed_value = value

    type_arg = f"'{_escape_py_string(parameter_type)}'" if parameter_type else "None"
    value_repr = repr(parsed_value)

    script = (
        f"result = material_helpers.set_instance_parameter("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(parameter_name)}', "
        f"{value_repr}, "
        f"{type_arg})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    ptype = data.get("parameter_type", parameter_type or "Unknown")
    lines = [
        f"Material Instance: {data.get('asset_path', asset_path)}",
        f"  Parameter: {data.get('parameter_name', parameter_name)} ({ptype})",
        f"  Old Value: {data.get('old_value', 'N/A')}",
        f"  New Value: {data.get('new_value', 'N/A')}",
        "  Updated successfully.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 12: create_material_expression
# ---------------------------------------------------------------------------

@mcp.tool()
def create_material_expression(
    asset_path: str,
    expression_class: str,
    node_pos_x: int = 0,
    node_pos_y: int = 0,
    properties: str | None = None,
) -> str:
    """Create a new expression node in a material graph.

    Args:
        asset_path: Unreal asset path to a material
        expression_class: Class name (e.g. 'ScalarParameter', 'TextureSample')
        node_pos_x: X position in the graph editor
        node_pos_y: Y position in the graph editor
        properties: Optional JSON string of properties, e.g. '{"parameter_name": "Roughness"}'
    """
    if properties is not None:
        try:
            props_dict = json.loads(properties)
        except (json.JSONDecodeError, TypeError):
            return f"Error: Invalid JSON for properties: {properties}"
        props_repr = repr(props_dict)
    else:
        props_repr = "None"

    script = (
        f"result = material_helpers.create_expression("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(expression_class)}', "
        f"node_pos_x={node_pos_x}, node_pos_y={node_pos_y}, "
        f"properties={props_repr})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    name = data.get("expression_name", "Unknown")
    cls = data.get("expression_class", expression_class)
    pos = data.get("position", {"x": node_pos_x, "y": node_pos_y})

    lines = [
        f"Created: {name} ({cls})",
        f"  Position: ({pos.get('x', node_pos_x)}, {pos.get('y', node_pos_y)})",
        f"  Material: {data.get('asset_path', asset_path)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 13: delete_material_expression
# ---------------------------------------------------------------------------

@mcp.tool()
def delete_material_expression(asset_path: str, expression_name: str) -> str:
    """Delete an expression node from a material graph.

    Args:
        asset_path: Unreal asset path to a material
        expression_name: Name of the expression to delete
    """
    script = (
        f"result = material_helpers.delete_expression("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(expression_name)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Deleted: {data.get('expression_name', expression_name)}",
        f"  Material: {data.get('asset_path', asset_path)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 14: connect_material_expressions
# ---------------------------------------------------------------------------

@mcp.tool()
def connect_material_expressions(
    asset_path: str,
    from_expression: str,
    to_expression_or_property: str,
    from_output: str = "",
    to_input: str = "",
) -> str:
    """Connect two expression nodes or connect an expression to a material property.

    Args:
        asset_path: Unreal asset path to a material
        from_expression: Source expression name
        to_expression_or_property: Target expression name or material property (e.g. 'BaseColor')
        from_output: Output pin name on source (empty for default)
        to_input: Input pin name on target (empty for default)
    """
    script = (
        f"result = material_helpers.connect_expressions("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(from_expression)}', "
        f"'{_escape_py_string(to_expression_or_property)}', "
        f"from_output='{_escape_py_string(from_output)}', "
        f"to_input='{_escape_py_string(to_input)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    conn = data.get("connection_string", f"{from_expression} -> {to_expression_or_property}")
    conn_type = data.get("connection_type", "expression")

    lines = [
        f"Connected: {conn}",
        f"  Type: {conn_type}",
        f"  Material: {data.get('asset_path', asset_path)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 15: set_material_property
# ---------------------------------------------------------------------------

@mcp.tool()
def set_material_property(asset_path: str, property_name: str, value: str) -> str:
    """Set a top-level material property (blend mode, shading model, usage flags, etc.).

    Args:
        asset_path: Unreal asset path to a material
        property_name: Property name (e.g. 'blend_mode', 'two_sided', 'bUsedWithStaticLighting')
        value: New value as a string
    """
    try:
        parsed_value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        parsed_value = value

    value_repr = repr(parsed_value)

    script = (
        f"result = material_helpers.set_material_property("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(property_name)}', "
        f"{value_repr})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    # Usage flag style response
    if data.get("is_usage_flag"):
        enabled = "enabled" if data.get("new_value") else "disabled"
        lines = [
            f"Material: {data.get('asset_path', asset_path)}",
            f"  Usage {data.get('property_name', property_name)}: {enabled}",
        ]
    else:
        lines = [
            f"Material: {data.get('asset_path', asset_path)}",
            f"  {data.get('property_name', property_name)}: "
            f"{data.get('old_value', 'N/A')} -> {data.get('new_value', 'N/A')}",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 16: recompile_material
# ---------------------------------------------------------------------------

@mcp.tool()
def recompile_material(asset_path: str) -> str:
    """Force-recompile a material's shaders.

    Args:
        asset_path: Unreal asset path to a material
    """
    script = (
        f"result = material_helpers.recompile_material("
        f"'{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    return f"Recompiled: {data.get('asset_path', asset_path)}"


# ---------------------------------------------------------------------------
# Tool 17: layout_material_graph
# ---------------------------------------------------------------------------

@mcp.tool()
def layout_material_graph(asset_path: str) -> str:
    """Auto-layout the nodes in a material graph for readability.

    Args:
        asset_path: Unreal asset path to a material
    """
    script = (
        f"result = material_helpers.layout_material_graph("
        f"'{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    return f"Layout applied: {data.get('asset_path', asset_path)}"


# ---------------------------------------------------------------------------
# Tool 18: find_material_references
# ---------------------------------------------------------------------------

@mcp.tool()
def find_material_references(
    asset_path: str,
    base_path: str = "/Game",
    asset_types: str | None = None,
) -> str:
    """Find all assets that reference a given material or material instance.

    Returns meshes, blueprints, Niagara systems, and other assets that
    depend on this material.

    Args:
        asset_path: Unreal asset path to a material or MI
        base_path: Narrow search scope (default '/Game')
        asset_types: Optional comma-separated filter (e.g. 'StaticMesh,SkeletalMesh')
    """
    types_arg = f"'{_escape_py_string(asset_types)}'" if asset_types else "None"
    script = (
        f"result = material_helpers.find_references("
        f"'{_escape_py_string(asset_path)}', "
        f"base_path='{_escape_py_string(base_path)}', "
        f"asset_types={types_arg})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    refs = data.get("references", [])
    total = data.get("total_found", len(refs))
    scanned = data.get("packages_scanned", 0)

    lines = [
        f"References to {data.get('asset_path', asset_path)} "
        f"({total} references, {scanned} packages scanned):",
    ]

    if not refs:
        lines.append("  No references found.")
    else:
        # Group by type
        groups: dict[str, list] = {}
        for r in refs:
            atype = r.get("asset_type", "Unknown")
            groups.setdefault(atype, []).append(r)

        for atype in sorted(groups.keys()):
            items = groups[atype]
            lines.append(f"  [{atype}] ({len(items)})")
            for r in items:
                lines.append(f"    {r.get('asset_path', '?')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 19: find_breaking_changes
# ---------------------------------------------------------------------------

@mcp.tool()
def find_breaking_changes(
    asset_path: str,
    parameter_name: str | None = None,
    expression_name: str | None = None,
    base_path: str = "/Game",
) -> str:
    """Analyze what would break if a parameter or expression were removed.

    Args:
        asset_path: Base material path
        parameter_name: Parameter to check removal of
        expression_name: Expression to check removal of
        base_path: Scope for child instance search
    """
    param_arg = f"'{_escape_py_string(parameter_name)}'" if parameter_name else "None"
    expr_arg = f"'{_escape_py_string(expression_name)}'" if expression_name else "None"

    script = (
        f"result = material_helpers.find_breaking_changes("
        f"'{_escape_py_string(asset_path)}', "
        f"parameter_name={param_arg}, "
        f"expression_name={expr_arg}, "
        f"base_path='{_escape_py_string(base_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    target = data.get("target", "?")
    target_type = data.get("target_type", "?")
    instances = data.get("affected_instances", [])
    connections = data.get("downstream_connections", [])

    lines = [
        f"Breaking change analysis for removing {target_type} '{target}' "
        f"from {data.get('asset_path', asset_path)}:",
    ]

    if not instances and not connections:
        lines.append("  No breaking changes detected.")
        return "\n".join(lines)

    if instances:
        lines.append(f"  Affected instances ({len(instances)}):")
        for inst in instances:
            val = inst.get("override_value", "?")
            lines.append(f"    {inst.get('path', '?')} (override: {val})")

    if connections:
        lines.append(f"  Downstream connections ({len(connections)}):")
        for conn in connections:
            expr = conn.get("expression", conn.get("output_pin", "?"))
            note = conn.get("note", "")
            inp = conn.get("input", "")
            if inp:
                lines.append(f"    → {expr} (input {inp})")
            else:
                lines.append(f"    → {expr}: {note}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 20: find_material_function_usage
# ---------------------------------------------------------------------------

@mcp.tool()
def find_material_function_usage(
    function_path: str,
    base_path: str = "/Game",
    include_chain: bool = False,
) -> str:
    """Find which materials use a material function, and optionally trace its call chain.

    Args:
        function_path: MaterialFunction asset path
        base_path: Scope for material search
        include_chain: Include nested function dependency tree
    """
    script = (
        f"result = material_helpers.find_function_usage("
        f"'{_escape_py_string(function_path)}', "
        f"base_path='{_escape_py_string(base_path)}', "
        f"include_chain={include_chain})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    materials = data.get("materials_using", [])
    lines = [
        f"Usage of {data.get('function_path', function_path)} ({len(materials)} materials):",
    ]

    if not materials:
        lines.append("  No materials found using this function.")
    else:
        for m in materials:
            lines.append(f"  {m.get('material', '?')} → {m.get('expression', '?')}")

    chain = data.get("call_chain")
    if chain:
        lines.append("  Call chain:")
        def _format_chain(node, indent=2):
            prefix = "  " * indent
            name = node.get("name", "?")
            result_lines = [f"{prefix}{name}"]
            for child in node.get("children", []):
                result_lines.extend(_format_chain(child, indent + 1))
            return result_lines
        lines.extend(_format_chain(chain))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 21: search_material_instances
# ---------------------------------------------------------------------------

@mcp.tool()
def search_material_instances(
    base_path: str = "/Game",
    parent_path: str | None = None,
    filter_type: str = "all",
) -> str:
    """Search for material instances with filters: by parent, dead (no overrides), orphaned.

    Args:
        base_path: Content path to search under
        parent_path: Filter by parent (for 'by_parent' filter)
        filter_type: One of 'all', 'by_parent', 'dead', 'orphaned'
    """
    parent_arg = f"'{_escape_py_string(parent_path)}'" if parent_path else "None"
    script = (
        f"result = material_helpers.search_instances("
        f"base_path='{_escape_py_string(base_path)}', "
        f"parent_path={parent_arg}, "
        f"filter_type='{_escape_py_string(filter_type)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    results = data.get("results", [])
    scanned = data.get("total_scanned", 0)
    ft = data.get("filter_type", filter_type)

    lines = [
        f"Material instances [{ft}] under {data.get('base_path', base_path)} "
        f"({len(results)} found, {scanned} scanned):",
    ]

    if not results:
        lines.append("  No instances found.")
    else:
        for r in results:
            parent = r.get("parent", "?")
            overrides = r.get("override_count", 0)
            lines.append(f"  {r.get('path', '?')} (parent: {parent}, {overrides} overrides)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 22: set_expression_property
# ---------------------------------------------------------------------------

@mcp.tool()
def set_expression_property(
    asset_path: str,
    expression_name: str,
    property_name: str,
    value: str,
) -> str:
    """Set a property on an existing material expression node.

    Args:
        asset_path: Base material path
        expression_name: Expression to modify (e.g. 'MaterialExpressionScalarParameter_0')
        property_name: Property to set (e.g. 'parameter_name', 'texture', 'code')
        value: New value as string (JSON for complex types)
    """
    try:
        parsed_value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        parsed_value = value

    value_repr = repr(parsed_value)

    script = (
        f"result = material_helpers.set_expression_property("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(expression_name)}', "
        f"'{_escape_py_string(property_name)}', "
        f"{value_repr})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Expression: {data.get('expression_name', expression_name)}",
        f"  Property: {data.get('property_name', property_name)}",
        f"  Old: {data.get('old_value', 'N/A')}",
        f"  New: {data.get('new_value', 'N/A')}",
        f"  Material: {data.get('asset_path', asset_path)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server (stdio transport)."""
    mcp.run()
