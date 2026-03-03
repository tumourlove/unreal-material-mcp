"""MCP server with 5 tools for UE Material graph intelligence."""

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
        "Provides read-only intelligence for Unreal Engine material graphs. "
        "Use these tools to inspect material properties, parameters, node graphs, "
        "and search for materials in an Unreal project."
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
        _bridge = EditorBridge()
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

    # Handle list output (some bridge versions return a list of lines)
    if isinstance(output, list):
        output = "\n".join(str(line) for line in output)

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
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server (stdio transport)."""
    mcp.run()
