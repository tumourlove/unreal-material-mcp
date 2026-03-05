"""MCP server with 40+ tools for UE Material graph intelligence."""

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
# Track recently deleted expression names per material to filter stale
# disconnect warnings (UE keeps deleted objects alive until GC).
_recently_deleted: dict[str, set[str]] = {}


def _reset_state() -> None:
    """Reset module singletons (used by tests)."""
    global _bridge, _helper_uploaded, _helper_hash, _project_path, _recently_deleted
    _bridge = None
    _helper_uploaded = False
    _helper_hash = ""
    _project_path = UE_PROJECT_PATH
    _recently_deleted = {}


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
            if isinstance(s, str):
                lines.append(f"    {s}")
            elif isinstance(s, dict):
                source_path = s.get("source", "local")
                if source_path not in ("local", None):
                    lines.append(f"    {s.get('name', '?')} ({s.get('type', '?')}) -> {source_path}")
                else:
                    lines.append(f"    {s.get('name', '?')} (local)")
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

    prop_diff = data.get("property_diff", [])
    if prop_diff:
        lines.append("  Property Differences:")
        if isinstance(prop_diff, list):
            for entry in prop_diff:
                key = entry.get("property", "?")
                lines.append(f"    {key}: {entry.get('a', 'N/A')} -> {entry.get('b', 'N/A')}")
        else:
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
    properties: str | dict | None = None,
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
        if isinstance(properties, dict):
            props_dict = properties
        else:
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
    global _recently_deleted

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

    # Track this deletion to filter stale warnings in subsequent deletes
    deleted_name = data.get("expression_name", expression_name)
    if not deleted_name.startswith("MaterialExpression"):
        deleted_name = f"MaterialExpression{deleted_name}"
    deleted_set = _recently_deleted.setdefault(asset_path, set())
    deleted_set.add(deleted_name)

    lines = [
        f"Deleted: {data.get('expression_name', expression_name)}",
        f"  Material: {data.get('asset_path', asset_path)}",
    ]
    if data.get("disconnected"):
        # Filter out warnings about expressions we've already deleted
        live_disconnected = [
            entry for entry in data["disconnected"]
            if entry["expression"] not in deleted_set
        ]
        if live_disconnected:
            lines.append(f"  Warning: Disconnected {len(live_disconnected)} input(s) on other expressions")
            for entry in live_disconnected:
                lines.append(f"    - {entry['expression']} input {entry['input']}")
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
    if data.get("warning"):
        lines.append(f"  Warning: {data['warning']}")
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
        f"result = material_helpers.set_property("
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
        f"result = material_helpers.recompile("
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
        f"result = material_helpers.layout_graph("
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
# Tool 23: duplicate_expression_subgraph
# ---------------------------------------------------------------------------

@mcp.tool()
def duplicate_expression_subgraph(
    asset_path: str,
    root_expression: str,
    offset_x: int = 0,
    offset_y: int = 300,
) -> str:
    """Duplicate an expression and all its upstream inputs within the same material.

    Args:
        asset_path: Base material path
        root_expression: Root expression to duplicate
        offset_x: X offset for duplicated nodes
        offset_y: Y offset for duplicated nodes
    """
    script = (
        f"result = material_helpers.duplicate_subgraph("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(root_expression)}', "
        f"offset_x={offset_x}, offset_y={offset_y})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    duped = data.get("duplicated", {})
    count = data.get("count", len(duped))

    lines = [
        f"Duplicated subgraph from {data.get('root_expression', root_expression)} ({count} nodes):",
        f"  Material: {data.get('asset_path', asset_path)}",
    ]
    for orig, new in duped.items():
        lines.append(f"  {orig} → {new}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 24: manage_material_parameter
# ---------------------------------------------------------------------------

@mcp.tool()
def manage_material_parameter(
    asset_path: str,
    action: str,
    parameter_name: str,
    new_name: str | None = None,
    parameter_type: str | None = None,
    default_value: str | None = None,
    group: str | None = None,
) -> str:
    """Add, remove, or rename a material parameter.

    Args:
        asset_path: Base material path
        action: 'add', 'remove', or 'rename'
        parameter_name: Target parameter name
        new_name: New name (for 'rename')
        parameter_type: Type for 'add' ('scalar', 'vector', 'texture', 'static_switch')
        default_value: Default value for 'add' (JSON for complex types)
        group: Parameter group for 'add'
    """
    parsed_default = None
    if default_value is not None:
        try:
            parsed_default = json.loads(default_value)
        except (json.JSONDecodeError, TypeError):
            parsed_default = default_value

    new_arg = f"'{_escape_py_string(new_name)}'" if new_name else "None"
    type_arg = f"'{_escape_py_string(parameter_type)}'" if parameter_type else "None"
    default_arg = repr(parsed_default) if parsed_default is not None else "None"
    group_arg = f"'{_escape_py_string(group)}'" if group else "None"

    script = (
        f"result = material_helpers.manage_parameter("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(action)}', "
        f"'{_escape_py_string(parameter_name)}', "
        f"new_name={new_arg}, "
        f"parameter_type={type_arg}, "
        f"default_value={default_arg}, "
        f"group={group_arg})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    act = data.get("action", action)
    if act == "add":
        lines = [
            f"Added parameter: {data.get('parameter_name', parameter_name)} "
            f"({data.get('parameter_type', parameter_type)})",
            f"  Expression: {data.get('expression_name', 'N/A')}",
            f"  Material: {data.get('asset_path', asset_path)}",
        ]
    elif act == "remove":
        lines = [
            f"Removed parameter: {data.get('parameter_name', parameter_name)}",
            f"  Expression: {data.get('expression_name', 'N/A')}",
            f"  Material: {data.get('asset_path', asset_path)}",
        ]
    elif act == "rename":
        lines = [
            f"Renamed: {data.get('old_name', parameter_name)} → {data.get('new_name', new_name)}",
            f"  Material: {data.get('asset_path', asset_path)}",
        ]
    else:
        lines = [f"Action: {act} completed"]

    return "\n".join(lines)


@mcp.tool()
def rename_parameter_cascade(
    asset_path: str,
    old_name: str,
    new_name: str,
    base_path: str = "/Game",
) -> str:
    """Rename a parameter across a material and all its child instances."""
    script = (
        f"result = material_helpers.rename_parameter_cascade("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(old_name)}', "
        f"'{_escape_py_string(new_name)}', "
        f"base_path='{_escape_py_string(base_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Renamed: {data.get('old_name', old_name)} → {data.get('new_name', new_name)}",
        f"  Material: {data.get('asset_path', asset_path)}",
        f"  Instances updated: {data.get('instances_updated', 0)} / {data.get('instances_scanned', 0)} scanned",
    ]
    return "\n".join(lines)


@mcp.tool()
def create_material_instance(
    parent_path: str,
    instance_name: str,
    destination_path: str = "",
) -> str:
    """Create a new material instance from a parent material.

    Args:
        parent_path: Parent material or MI path
        instance_name: Name for the new MI
        destination_path: Content path (default: same dir as parent)
    """
    dest_arg = f"'{_escape_py_string(destination_path)}'" if destination_path else "''"
    script = (
        f"result = material_helpers.create_instance("
        f"'{_escape_py_string(parent_path)}', "
        f"'{_escape_py_string(instance_name)}', "
        f"destination_path={dest_arg})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Created: {data.get('instance_path', instance_name)}",
        f"  Parent: {data.get('parent_path', parent_path)}",
    ]
    return "\n".join(lines)


@mcp.tool()
def reparent_material_instance(
    instance_path: str,
    new_parent_path: str,
) -> str:
    """Reparent a material instance to a different parent material.

    Args:
        instance_path: MI to reparent
        new_parent_path: New parent material or MI
    """
    script = (
        f"result = material_helpers.reparent_instance("
        f"'{_escape_py_string(instance_path)}', "
        f"'{_escape_py_string(new_parent_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Reparented: {data.get('instance_path', instance_path)}",
        f"  Old parent: {data.get('old_parent', 'N/A')}",
        f"  New parent: {data.get('new_parent', new_parent_path)}",
    ]
    return "\n".join(lines)


@mcp.tool()
def batch_update_materials(
    base_path: str,
    operation: str,
    filter_query: str = "",
    filter_type: str = "name",
    operation_args: str = "{}",
) -> str:
    """Batch update materials: swap textures, set parameters, or set attributes.

    Args:
        base_path: Content path to search under
        operation: 'swap_texture', 'set_parameter', or 'set_attribute'
        filter_query: Filter string for targeting materials
        filter_type: 'name', 'parameter', 'expression', 'shading_model'
        operation_args: JSON string with operation-specific args
    """
    try:
        args_dict = json.loads(operation_args)
    except (json.JSONDecodeError, TypeError):
        return f"Error: Invalid JSON for operation_args: {operation_args}"

    args_repr = repr(args_dict)

    script = (
        f"result = material_helpers.batch_update("
        f"'{_escape_py_string(base_path)}', "
        f"'{_escape_py_string(operation)}', "
        f"filter_query='{_escape_py_string(filter_query)}', "
        f"filter_type='{_escape_py_string(filter_type)}', "
        f"operation_args={args_repr})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    op = data.get("operation", operation)
    processed = data.get("processed", 0)
    modified = data.get("modified", 0)
    assets = data.get("modified_assets", [])
    errors = data.get("errors", [])

    lines = [
        f"Batch {op}: {modified} modified out of {processed} processed",
    ]

    if assets:
        lines.append("  Modified:")
        for a in assets:
            lines.append(f"    {a}")

    if errors:
        lines.append(f"  Errors ({len(errors)}):")
        for e in errors:
            lines.append(f"    {e.get('path', '?')}: {e.get('error', '?')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 29: create_material
# ---------------------------------------------------------------------------

@mcp.tool()
def create_material(
    asset_path: str,
    blend_mode: str = "Opaque",
    shading_model: str = "DefaultLit",
    material_domain: str = "Surface",
    two_sided: bool = False,
) -> str:
    """Create a new base Material asset from scratch.

    Args:
        asset_path: Save path, e.g. '/Game/Materials/M_NewMaterial'
        blend_mode: Blend mode (Opaque, Masked, Translucent, etc.)
        shading_model: Shading model (DefaultLit, Unlit, SubsurfaceProfile, etc.)
        material_domain: Material domain (Surface, DeferredDecal, PostProcess, etc.)
        two_sided: Whether the material renders on both sides
    """
    script = (
        f"result = material_helpers.create_material("
        f"'{_escape_py_string(asset_path)}', "
        f"blend_mode='{_escape_py_string(blend_mode)}', "
        f"shading_model='{_escape_py_string(shading_model)}', "
        f"material_domain='{_escape_py_string(material_domain)}', "
        f"two_sided={two_sided})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    lines = [
        f"Created: {data.get('asset_path', asset_path)}",
        f"  Blend Mode: {data.get('blend_mode', 'N/A')}",
        f"  Shading Model: {data.get('shading_model', 'N/A')}",
        f"  Domain: {data.get('material_domain', 'N/A')}",
        f"  Two Sided: {data.get('two_sided', False)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 30: duplicate_material
# ---------------------------------------------------------------------------

@mcp.tool()
def duplicate_material(source_path: str, destination_path: str) -> str:
    """Deep-copy a material to a new asset path.

    Args:
        source_path: Source material path
        destination_path: Destination path for the copy
    """
    script = (
        f"result = material_helpers.duplicate_material("
        f"'{_escape_py_string(source_path)}', "
        f"'{_escape_py_string(destination_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    return f"Duplicated {data.get('source_path')} -> {data.get('destination_path')}"


# ---------------------------------------------------------------------------
# Tool 31: save_material
# ---------------------------------------------------------------------------

@mcp.tool()
def save_material(asset_path: str) -> str:
    """Save a material asset to disk.

    Args:
        asset_path: Material asset path
    """
    script = (
        f"result = material_helpers.save_material('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    return f"Saved: {data.get('asset_path')} (success: {data.get('saved', False)})"


# ---------------------------------------------------------------------------
# Tool 32: disconnect_expressions
# ---------------------------------------------------------------------------

@mcp.tool()
def disconnect_expressions(
    asset_path: str,
    expression_name: str,
    input_name: str = "",
    disconnect_outputs: bool = False,
) -> str:
    """Disconnect wires on an expression without deleting it.

    Args:
        asset_path: Material asset path
        expression_name: Name of the expression to disconnect
        input_name: Specific input pin to disconnect (empty = all inputs)
        disconnect_outputs: If True, disconnect downstream connections instead of inputs
    """
    script = (
        f"result = material_helpers.disconnect_expressions("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(expression_name)}', "
        f"input_name='{_escape_py_string(input_name)}', "
        f"disconnect_outputs={disconnect_outputs})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    count = data.get("count", 0)
    lines = [f"Disconnected {count} wire(s) on {expression_name}"]
    for d in data.get("disconnected", []):
        lines.append(f"  {d.get('pin', '?')}: was connected to {d.get('was_connected_to', d.get('expression', '?'))}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 33: create_custom_hlsl_node
# ---------------------------------------------------------------------------

@mcp.tool()
def create_custom_hlsl_node(
    asset_path: str,
    code: str,
    description: str = "",
    output_type: str = "Float3",
    inputs: str = "[]",
    additional_outputs: str = "[]",
    pos_x: int = 0,
    pos_y: int = 0,
) -> str:
    """Create a Custom HLSL expression node with code, inputs, and outputs.

    Args:
        asset_path: Material asset path
        code: HLSL code for the custom node
        description: Description label for the node
        output_type: Main output type (Float1, Float2, Float3, Float4)
        inputs: JSON array of input definitions, e.g. [{"name": "UV"}]
        additional_outputs: JSON array of extra outputs, e.g. [{"name": "Mask", "type": "Float1"}]
        pos_x: X position in the material graph
        pos_y: Y position in the material graph
    """
    script = (
        f"result = material_helpers.create_custom_hlsl("
        f"'{_escape_py_string(asset_path)}', "
        f"'''{_escape_py_string(code)}''', "
        f"description='{_escape_py_string(description)}', "
        f"output_type='{_escape_py_string(output_type)}', "
        f"inputs_json='{_escape_py_string(inputs)}', "
        f"additional_outputs_json='{_escape_py_string(additional_outputs)}', "
        f"pos_x={pos_x}, pos_y={pos_y})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    lines = [
        f"Created Custom HLSL: {data.get('expression_name', '?')}",
        f"  Output Type: {data.get('output_type', output_type)}",
        f"  Inputs: {data.get('input_count', 0)}",
        f"  Additional Outputs: {data.get('additional_output_count', 0)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 34: get_expression_details
# ---------------------------------------------------------------------------

@mcp.tool()
def get_expression_details(asset_path: str, expression_name: str) -> str:
    """Get detailed information about a single expression node including all properties, inputs, and outputs.

    Args:
        asset_path: Material asset path
        expression_name: Name of the expression (e.g. 'MaterialExpressionMultiply_0')
    """
    script = (
        f"result = material_helpers.get_expression_details("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(expression_name)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    lines = [
        f"Expression: {data.get('expression_name', expression_name)}",
        f"  Class: {data.get('class', '?')}",
    ]
    props = data.get("properties", {})
    if props:
        lines.append("  Properties:")
        for k, v in list(props.items())[:30]:  # Limit to 30 most relevant
            lines.append(f"    {k}: {v}")
        if len(props) > 30:
            lines.append(f"    ... and {len(props) - 30} more")
    inputs = data.get("inputs", [])
    if inputs:
        lines.append("  Inputs:")
        for inp in inputs:
            conn = f" -> {inp.get('connected_to', '?')}" if inp.get("connected") else " (disconnected)"
            lines.append(f"    {inp.get('name', '?')}{conn}")
    outputs = data.get("outputs", [])
    if outputs:
        lines.append("  Outputs:")
        for out in outputs:
            lines.append(f"    [{out.get('index', '?')}] {out.get('name', '?')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 35: get_material_layer_info
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_layer_info(asset_path: str) -> str:
    """Get Material Layer or Material Layer Blend info.

    Args:
        asset_path: Asset path of the material function/layer
    """
    script = (
        f"result = material_helpers.get_layer_info('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    lines = [
        f"Asset: {data.get('asset_path', asset_path)}",
        f"  Type: {data.get('type', '?')}",
        f"  Description: {data.get('description', 'N/A')}",
        f"  Expressions: {data.get('expression_count', 0)}",
    ]
    for inp in data.get("inputs", []):
        lines.append(f"  Input: {inp.get('name', '?')} (priority: {inp.get('sort_priority', 0)})")
    for out in data.get("outputs", []):
        lines.append(f"  Output: {out.get('name', '?')} (priority: {out.get('sort_priority', 0)})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 36: validate_material
# ---------------------------------------------------------------------------

@mcp.tool()
def validate_material(asset_path: str, fix_issues: bool = False) -> str:
    """Validate material graph health: find islands, broken refs, duplicate params, unused nodes.

    Args:
        asset_path: Material asset path
        fix_issues: If True, attempt to auto-fix issues (delete islands, etc.)
    """
    script = (
        f"result = material_helpers.validate_material("
        f"'{_escape_py_string(asset_path)}', "
        f"fix_issues={fix_issues})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    issues = data.get("issues", [])
    fixed = data.get("fixed_count", 0)
    lines = [f"Validation: {data.get('asset_path', asset_path)}"]
    lines.append(f"  Issues found: {len(issues)}")
    if fixed:
        lines.append(f"  Issues fixed: {fixed}")
    for issue in issues:
        severity = issue.get("severity", "?").upper()
        msg = issue.get("message", issue.get("type", "?"))
        expr = issue.get("expression", "")
        fixed_flag = " [FIXED]" if issue.get("fixed") else ""
        lines.append(f"  [{severity}] {msg}{': ' + expr if expr else ''}{fixed_flag}")
    if not issues:
        lines.append("  No issues found!")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 37: export_material_graph
# ---------------------------------------------------------------------------

@mcp.tool()
def export_material_graph(asset_path: str, export_name: str = "") -> str:
    """Export a material's complete node graph to a JSON file for backup or transfer.

    Args:
        asset_path: Material asset path
        export_name: Custom name for the export file (defaults to material name)
    """
    script = (
        f"result = material_helpers.export_graph('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    nodes = len(data.get("nodes", []))
    conns = len(data.get("connections", []))
    lines = [
        f"Exported: {data.get('asset_path', asset_path)}",
        f"  Nodes: {nodes}",
        f"  Connections: {conns}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 38: import_material_graph
# ---------------------------------------------------------------------------

@mcp.tool()
def import_material_graph(
    asset_path: str,
    graph_json: str,
    mode: str = "overwrite",
) -> str:
    """Import a material graph from a JSON spec. Use with export_material_graph for backup/transfer.

    Args:
        asset_path: Target material asset path
        graph_json: JSON string with the graph spec (from export_material_graph)
        mode: 'overwrite' replaces existing graph, 'merge' adds to existing
    """
    script = (
        f"result = material_helpers.import_graph("
        f"'{_escape_py_string(asset_path)}', "
        f"'''{_escape_py_string(graph_json)}''', "
        f"mode='{_escape_py_string(mode)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    lines = [
        f"Imported to: {data.get('asset_path', asset_path)}",
        f"  Mode: {mode}",
        f"  Nodes created: {data.get('nodes_created', 0)}",
        f"  Connections made: {data.get('connections_made', 0)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 39: copy_material_graph
# ---------------------------------------------------------------------------

@mcp.tool()
def copy_material_graph(
    source_path: str,
    destination_path: str,
) -> str:
    """Copy the entire node graph from one material to another (merge mode).

    Args:
        source_path: Source material to copy from
        destination_path: Destination material to paste into
    """
    script = (
        f"result = material_helpers.copy_material_graph("
        f"'{_escape_py_string(source_path)}', "
        f"'{_escape_py_string(destination_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    lines = [
        f"Copied graph: {source_path} -> {destination_path}",
        f"  Nodes created: {data.get('nodes_created', 0)}",
        f"  Connections made: {data.get('connections_made', 0)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 40: run_material_script
# ---------------------------------------------------------------------------

@mcp.tool()
def run_material_script(code: str) -> str:
    """Execute arbitrary Python in the editor with material_helpers pre-imported.

    The material_helpers module is available as 'material_helpers'.
    The 'unreal' and 'json' modules are also imported.
    Must print output to stdout.

    Args:
        code: Python code to execute
    """
    _ensure_helper_uploaded()
    saved_dir = _project_path.replace("\\", "/") + "/Saved/MaterialMCP"
    preamble = (
        "import sys, json\n"
        f"sys.path.insert(0, '{saved_dir}')\n"
        "import importlib, material_helpers\n"
        "importlib.reload(material_helpers)\n"
    )
    full_script = preamble + code
    bridge = _get_bridge()
    result = bridge.run_command(full_script)
    output = result.get("output", "") or result.get("result", "") or ""
    if isinstance(output, list):
        parts = []
        for item in output:
            if isinstance(item, dict):
                parts.append(item.get("output", str(item)))
            else:
                parts.append(str(item))
        output = "\n".join(parts)
    return str(output).strip()


# ---------------------------------------------------------------------------
# Tool 41: build_material_graph
# ---------------------------------------------------------------------------

@mcp.tool()
def build_material_graph(
    asset_path: str,
    graph_spec: str,
    clear_existing: bool = False,
) -> str:
    """Build an entire material node graph from a declarative JSON spec in one call.

    The spec defines nodes with IDs, connections between them, and material output wiring.
    Uses native C++ for speed when the MaterialMCPReader plugin is available.

    Example spec:
    {
        "nodes": [
            {"id": "const", "class": "Constant3Vector", "pos": [-400, 0],
             "props": {"Constant": "(R=1.0,G=0.0,B=0.0)"}},
            {"id": "mul", "class": "Multiply", "pos": [-200, 0]}
        ],
        "connections": [
            {"from": "const", "to": "mul", "from_pin": "", "to_pin": "A"}
        ],
        "outputs": [
            {"from": "mul", "from_pin": "", "to_property": "BaseColor"}
        ]
    }

    Args:
        asset_path: Material to build graph in
        graph_spec: JSON string with nodes, connections, outputs arrays
        clear_existing: If True, delete all existing expressions first
    """
    try:
        spec = json.loads(graph_spec)
    except (json.JSONDecodeError, TypeError):
        return "Error: Invalid JSON for graph_spec"

    script = (
        f"spec = {repr(spec)}\n"
        f"result = material_helpers.build_graph_from_spec("
        f"'{_escape_py_string(asset_path)}', "
        f"json.dumps(spec), "
        f"clear_existing={clear_existing})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Material: {data.get('asset_path', asset_path)}",
        f"  Nodes created: {data.get('nodes_created', 0)}",
        f"  Connections made: {data.get('connections_made', 0)}",
    ]

    id_map = data.get("id_to_name", {})
    if id_map:
        lines.append("  ID -> Expression mapping:")
        for spec_id, expr_name in id_map.items():
            lines.append(f"    {spec_id} -> {expr_name}")

    errors = data.get("errors", [])
    if errors:
        lines.append(f"  Errors ({len(errors)}):")
        for e in errors:
            lines.append(f"    {e.get('node_id', e.get('id', '?'))}: {e.get('error', '?')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 42: list_material_templates
# ---------------------------------------------------------------------------

@mcp.tool()
def list_material_templates() -> str:
    """List all available material graph templates that can be used with create_subgraph_from_template."""
    from unreal_material_mcp.templates.material_templates import list_templates
    templates = list_templates()
    lines = ["Available templates:"]
    for name, desc in templates.items():
        lines.append(f"  {name}: {desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 43: create_subgraph_from_template
# ---------------------------------------------------------------------------

@mcp.tool()
def create_subgraph_from_template(
    asset_path: str,
    template_name: str,
    params: str = "{}",
    node_pos_x: int = 0,
    node_pos_y: int = 0,
) -> str:
    """Create a pre-built procedural material pattern as a subgraph.

    Available templates: noise_blend, pbr_texture_set, fresnel_glow.
    Use list_material_templates to see descriptions.

    Args:
        asset_path: Material to add subgraph to
        template_name: Template identifier
        params: JSON string with template-specific parameter overrides
        node_pos_x: X offset for the subgraph position
        node_pos_y: Y offset for the subgraph position
    """
    from unreal_material_mcp.templates.material_templates import get_template_spec, list_templates

    try:
        template_params = json.loads(params)
    except (json.JSONDecodeError, TypeError):
        return "Error: Invalid JSON for params"

    spec = get_template_spec(template_name, template_params)
    if spec is None:
        available = ", ".join(list_templates().keys())
        return f"Error: Unknown template '{template_name}'. Available: {available}"

    # Apply position offset to all nodes
    for node in spec.get("nodes", []):
        pos = node.get("pos", [0, 0])
        node["pos"] = [pos[0] + node_pos_x, pos[1] + node_pos_y]
    for node in spec.get("custom_hlsl_nodes", []):
        pos = node.get("pos", [0, 0])
        node["pos"] = [pos[0] + node_pos_x, pos[1] + node_pos_y]

    script = (
        f"spec = {repr(spec)}\n"
        f"result = material_helpers.build_graph_from_spec("
        f"'{_escape_py_string(asset_path)}', "
        f"json.dumps(spec), "
        f"clear_existing=False)\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"

    exposed = spec.get("_exposed_params", [])
    output_node = spec.get("_output_node", "")

    lines = [
        f"Template: {template_name}",
        f"  Nodes created: {data.get('nodes_created', 0)}",
        f"  Connections made: {data.get('connections_made', 0)}",
    ]
    if exposed:
        lines.append(f"  Exposed parameters: {', '.join(exposed)}")
    if output_node:
        mapped_name = data.get("id_to_name", {}).get(output_node, output_node)
        lines.append(f"  Output node: {mapped_name}")
        lines.append("  Wire this to a material output or another subgraph.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 44: preview_material
# ---------------------------------------------------------------------------

@mcp.tool()
def preview_material(asset_path: str, resolution: int = 256) -> str:
    """Render a material preview and save to PNG.

    Args:
        asset_path: Material asset path
        resolution: Preview image resolution (default 256)
    """
    script = (
        f"result = material_helpers.render_preview("
        f"'{_escape_py_string(asset_path)}', resolution={resolution})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    return f"Preview saved: {data.get('file_path', 'N/A')} ({data.get('width', '?')}x{data.get('height', '?')})"


# ---------------------------------------------------------------------------
# Tool 45: get_material_thumbnail
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_thumbnail(asset_path: str, resolution: int = 256) -> str:
    """Get material thumbnail as base64-encoded PNG data.

    Args:
        asset_path: Material asset path
        resolution: Thumbnail resolution (default 256)
    """
    script = (
        f"result = material_helpers.get_thumbnail("
        f"'{_escape_py_string(asset_path)}', resolution={resolution})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"
    data_len = len(data.get("data", ""))
    return f"Thumbnail: {data.get('width', '?')}x{data.get('height', '?')} ({data_len} bytes base64)"


# ---------------------------------------------------------------------------
# Tool 46: create_material_from_textures
# ---------------------------------------------------------------------------

@mcp.tool()
def create_material_from_textures(
    asset_path: str,
    textures: str,
    tiling: float = 1.0,
) -> str:
    """Auto-build a complete PBR material from texture paths.

    Args:
        asset_path: Path for the new material
        textures: JSON object mapping channels to texture paths, e.g.:
            {"base_color": "/Game/T_Albedo", "normal": "/Game/T_Normal", "roughness": "/Game/T_Roughness"}
            Supported channels: base_color, normal, roughness, metallic, ao, emissive, opacity
    """
    try:
        tex_dict = json.loads(textures)
    except (json.JSONDecodeError, TypeError):
        return "Error: Invalid JSON for textures"

    # Build a graph spec from the textures
    nodes = [
        {"id": "tiling_param", "class": "ScalarParameter", "pos": [-1200, 0],
         "props": {"ParameterName": "Tiling", "DefaultValue": str(tiling)}},
        {"id": "texcoord", "class": "TextureCoordinate", "pos": [-1000, 0]},
        {"id": "uv_multiply", "class": "Multiply", "pos": [-800, 0]},
    ]
    connections = [
        {"from": "tiling_param", "from_pin": "", "to": "uv_multiply", "to_pin": "A"},
        {"from": "texcoord", "from_pin": "", "to": "uv_multiply", "to_pin": "B"},
    ]
    outputs = []

    channel_map = {
        "base_color": ("BaseColor", "RGB", -400),
        "normal": ("Normal", "RGB", -200),
        "roughness": ("Roughness", "R", 0),
        "metallic": ("Metallic", "R", 100),
        "ao": ("AmbientOcclusion", "R", 200),
        "emissive": ("EmissiveColor", "RGB", 300),
        "opacity": ("Opacity", "R", 400),
    }

    for channel, tex_path in tex_dict.items():
        if channel not in channel_map:
            continue
        mat_prop, out_pin, y_offset = channel_map[channel]
        node_id = f"tex_{channel}"
        nodes.append({
            "id": node_id,
            "class": "TextureSampleParameter2D",
            "pos": [-500, y_offset],
            "props": {"ParameterName": channel.replace("_", " ").title()},
        })
        connections.append({"from": "uv_multiply", "from_pin": "", "to": node_id, "to_pin": "UVs"})
        outputs.append({"from": node_id, "from_pin": out_pin, "to_property": mat_prop})

    # First create the material, then build the graph
    create_script = (
        f"result = material_helpers.create_material('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    create_data = _run_material_script(create_script)
    create_err = _format_error(create_data)
    if create_err:
        return f"Error creating material: {create_err}"

    spec = {"nodes": nodes, "connections": connections, "outputs": outputs}
    build_script = (
        f"spec = {repr(spec)}\n"
        f"result = material_helpers.build_graph_from_spec("
        f"'{_escape_py_string(asset_path)}', "
        f"json.dumps(spec), clear_existing=False)\n"
        "print(result)\n"
    )
    data = _run_material_script(build_script)
    err = _format_error(data)
    if err:
        return f"Error building graph: {err}"

    channels_used = [ch for ch in tex_dict.keys() if ch in channel_map]
    lines = [
        f"Created PBR material: {asset_path}",
        f"  Channels: {', '.join(channels_used)}",
        f"  Nodes: {data.get('nodes_created', 0)}",
        f"  Connections: {data.get('connections_made', 0)}",
        f"  Tiling parameter: {tiling}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server (stdio transport)."""
    mcp.run()
