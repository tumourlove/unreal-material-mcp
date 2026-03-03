# unreal-material-mcp Tier 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an MCP server with 5 read-only tools for inspecting UE material graphs via the editor Python bridge.

**Architecture:** Two-layer system — a Python MCP server sends short scripts to the UE editor via the remote execution protocol. A helper module uploaded to the editor's Saved/ directory handles expression scanning, connection tracing, and parameter extraction. The MCP tools are thin wrappers that format results as human-readable strings.

**Tech Stack:** Python 3.11+, FastMCP (`mcp>=1.0.0`), `uv` package manager, UE remote execution protocol (UDP multicast + TCP)

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/unreal_material_mcp/__init__.py`
- Create: `src/unreal_material_mcp/__main__.py`
- Create: `src/unreal_material_mcp/config.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "unreal-material-mcp"
version = "0.1.0"
description = "Material graph intelligence for Unreal Engine AI development via MCP"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0.0",
]

[project.scripts]
unreal-material-mcp = "unreal_material_mcp.__main__:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/unreal_material_mcp"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[dependency-groups]
dev = [
    "pytest>=8.0",
]
```

**Step 2: Create `src/unreal_material_mcp/__init__.py`**

```python
"""Material graph intelligence for Unreal Engine AI development."""
__version__ = "0.1.0"
```

**Step 3: Create `src/unreal_material_mcp/config.py`**

```python
"""Configuration for unreal-material-mcp."""

import os

UE_PROJECT_PATH = os.environ.get("UE_PROJECT_PATH", "")
UE_EDITOR_PYTHON_PORT = int(os.environ.get("UE_EDITOR_PYTHON_PORT", "6776"))
UE_MULTICAST_GROUP = os.environ.get("UE_MULTICAST_GROUP", "239.0.0.1")
UE_MULTICAST_PORT = int(os.environ.get("UE_MULTICAST_PORT", "6766"))
UE_MULTICAST_BIND = os.environ.get("UE_MULTICAST_BIND", "127.0.0.1")
```

**Step 4: Create `src/unreal_material_mcp/__main__.py`**

```python
"""Entry point for `python -m unreal_material_mcp` and `uvx unreal-material-mcp`."""

from __future__ import annotations

import argparse

from unreal_material_mcp import __version__


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="unreal-material-mcp",
        description="Material graph intelligence for Unreal Engine AI development.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    args = parser.parse_args()
    _run_server()


def _run_server() -> None:
    from unreal_material_mcp.server import main
    main()


if __name__ == "__main__":
    cli()
```

**Step 5: Install deps and verify import**

Run: `cd C:/Projects/unreal-material-mcp && uv sync`
Expected: dependencies installed successfully

Run: `cd C:/Projects/unreal-material-mcp && uv run python -c "from unreal_material_mcp import __version__; print(__version__)"`
Expected: `0.1.0`

**Step 6: Commit**

```bash
git add pyproject.toml src/
git commit -m "feat: project scaffolding with config, entry point, and pyproject.toml"
```

---

### Task 2: Editor Bridge

**Files:**
- Create: `src/unreal_material_mcp/editor_bridge.py`

**Step 1: Copy editor bridge from blueprint server and update import path**

Copy `C:\Projects\unreal-blueprint-mcp\src\unreal_blueprint_mcp\editor_bridge.py` to `src/unreal_material_mcp/editor_bridge.py`.

Change the import line from:
```python
from unreal_blueprint_mcp.config import (
```
to:
```python
from unreal_material_mcp.config import (
```

No other changes needed — the bridge is identical across servers.

**Step 2: Verify import**

Run: `cd C:/Projects/unreal-material-mcp && uv run python -c "from unreal_material_mcp.editor_bridge import EditorBridge; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/unreal_material_mcp/editor_bridge.py
git commit -m "feat: add editor bridge (UDP multicast discovery + TCP commands)"
```

---

### Task 3: Helper Module — material_helpers.py

This is the Python module that gets uploaded to the UE editor and runs in-process. It uses `unreal.MaterialEditingLibrary` directly.

**Files:**
- Create: `src/unreal_material_mcp/helpers/__init__.py` (empty)
- Create: `src/unreal_material_mcp/helpers/material_helpers.py`

**Step 1: Create empty `__init__.py`**

```python
```

**Step 2: Create `material_helpers.py`**

This file runs inside the UE editor Python environment. It must NOT import anything from our MCP package — only `unreal`, `json`, and stdlib.

```python
"""Material graph helper — runs inside UE editor Python environment.

Uploaded to {project}/Saved/MaterialMCP/ by the MCP server.
Do NOT import anything from unreal_material_mcp — only unreal + stdlib.
"""

import json

import unreal

mel = unreal.MaterialEditingLibrary

# ~35 known expression class names (without MaterialExpression prefix)
EXPRESSION_CLASSES = [
    # Math
    "Add", "Subtract", "Multiply", "Divide", "Clamp", "OneMinus", "Power",
    "Abs", "Floor", "Ceil", "Frac", "Fmod", "Min", "Max", "Dot", "CrossProduct",
    # Vector
    "ComponentMask", "AppendVector", "Normalize", "TransformPosition", "TransformVector",
    # Parameters
    "ScalarParameter", "VectorParameter",
    "TextureSampleParameter2D", "TextureSampleParameter2DArray",
    "TextureObjectParameter", "StaticSwitchParameter", "StaticBoolParameter",
    # Constants
    "Constant", "Constant2Vector", "Constant3Vector", "Constant4Vector", "StaticBool",
    # Texture
    "TextureSample", "TextureCoordinate",
    # Utility
    "LinearInterpolate", "If", "Custom", "MaterialFunctionCall", "Comment",
    "VertexColor", "Time", "Fresnel", "DepthFade",
    "WorldPosition", "PixelDepth", "SceneDepth", "ScreenPosition",
    # Misc
    "DepthOfFieldFunction", "SphereMask", "Distance", "Saturate",
    "CameraPositionWS", "ActorPositionWS", "ObjectRadius",
    "Panner", "Rotator", "BreakMaterialAttributes",
    "MakeMaterialAttributes", "ChannelMaskParameterColor",
    "Desaturation", "CameraVectorWS", "PixelNormalWS",
    "VertexNormalWS", "TwoSidedSign", "ObjectPositionWS",
]


def _get_asset_name(asset_path):
    """Extract asset name from path: '/Game/Foo/Bar' -> 'Bar'."""
    return asset_path.rsplit("/", 1)[-1]


def _get_expr_properties(expr):
    """Extract key properties from an expression based on its class."""
    cls = expr.get_class().get_name()
    props = {}

    # Position
    try:
        props["x"] = expr.get_editor_property("material_expression_editor_x")
        props["y"] = expr.get_editor_property("material_expression_editor_y")
    except Exception:
        props["x"] = 0
        props["y"] = 0

    # Description/comment for all nodes
    try:
        desc = expr.get_editor_property("desc")
        if desc:
            props["desc"] = str(desc)
    except Exception:
        pass

    # Class-specific properties
    if "Parameter" in cls:
        try:
            props["parameter_name"] = str(expr.get_editor_property("parameter_name"))
        except Exception:
            pass
        try:
            props["group"] = str(expr.get_editor_property("group"))
        except Exception:
            pass

    if cls == "MaterialExpressionComponentMask":
        for ch in ["r", "g", "b", "a"]:
            try:
                props[ch] = bool(expr.get_editor_property(ch))
            except Exception:
                pass

    if cls == "MaterialExpressionCustom":
        try:
            props["code"] = str(expr.get_editor_property("code"))[:500]
        except Exception:
            pass
        try:
            props["description"] = str(expr.get_editor_property("description"))
        except Exception:
            pass
        try:
            props["output_type"] = str(expr.get_editor_property("output_type"))
        except Exception:
            pass

    if cls == "MaterialExpressionConstant":
        try:
            props["value"] = float(expr.get_editor_property("r"))
        except Exception:
            pass

    if cls == "MaterialExpressionConstant3Vector":
        try:
            c = expr.get_editor_property("constant")
            props["value"] = {"r": c.r, "g": c.g, "b": c.b, "a": c.a}
        except Exception:
            pass

    if cls == "MaterialExpressionComment":
        try:
            props["text"] = str(expr.get_editor_property("text"))
        except Exception:
            pass
        try:
            props["size_x"] = int(expr.get_editor_property("size_x"))
            props["size_y"] = int(expr.get_editor_property("size_y"))
        except Exception:
            pass

    if cls == "MaterialExpressionTextureCoordinate":
        try:
            props["coordinate_index"] = int(expr.get_editor_property("coordinate_index"))
        except Exception:
            pass

    if cls == "MaterialExpressionStaticSwitchParameter":
        try:
            props["default_value"] = bool(expr.get_editor_property("default_value"))
        except Exception:
            pass

    if cls == "MaterialExpressionMaterialFunctionCall":
        try:
            mf = expr.get_editor_property("material_function")
            if mf:
                props["function"] = str(mf.get_path_name())
        except Exception:
            pass

    return props


def get_material_info(asset_path):
    """Get material attributes: blend mode, shading model, domain, flags."""
    mat = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not mat:
        return json.dumps({"error": True, "message": f"Asset not found: {asset_path}"})

    is_material = mat.get_class().get_name() in ("Material", "MaterialInstanceConstant")
    if not is_material:
        return json.dumps({"error": True, "message": f"Not a material: {asset_path} ({mat.get_class().get_name()})"})

    result = {"asset_path": asset_path, "class": mat.get_class().get_name()}

    if mat.get_class().get_name() == "MaterialInstanceConstant":
        try:
            parent = mat.get_editor_property("parent")
            result["parent"] = str(parent.get_path_name()) if parent else None
        except Exception:
            pass
        return json.dumps(result)

    # Material properties
    try:
        result["blend_mode"] = str(mat.get_editor_property("blend_mode"))
    except Exception:
        pass
    try:
        result["shading_model"] = str(mat.get_editor_property("shading_model"))
    except Exception:
        pass
    try:
        result["material_domain"] = str(mat.get_editor_property("material_domain"))
    except Exception:
        pass
    try:
        result["two_sided"] = bool(mat.get_editor_property("two_sided"))
    except Exception:
        pass
    try:
        result["expression_count"] = int(mel.get_num_material_expressions(mat))
    except Exception:
        pass

    # Usage flags
    usage_flags = [
        "b_used_with_skeletal_mesh", "b_used_with_static_lighting",
        "b_used_with_particle_sprites", "b_used_with_beam_trails",
        "b_used_with_mesh_particles", "b_used_with_niagara_sprites",
        "b_used_with_niagara_mesh_particles", "b_used_with_niagara_ribbons",
        "b_used_with_morph_targets", "b_used_with_instanced_static_meshes",
        "b_used_with_spline_meshes", "b_used_with_clothing",
    ]
    flags = {}
    for flag in usage_flags:
        try:
            val = mat.get_editor_property(flag)
            if val:
                flags[flag] = True
        except Exception:
            pass
    if flags:
        result["usage_flags"] = flags

    return json.dumps(result)


def get_all_parameters(asset_path):
    """Get all material parameters with types and defaults."""
    mat = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not mat:
        return json.dumps({"error": True, "message": f"Asset not found: {asset_path}"})

    params = []

    # Scalar parameters
    for name in mel.get_scalar_parameter_names(mat):
        name_str = str(name)
        p = {"name": name_str, "type": "scalar"}
        try:
            p["default"] = float(mel.get_material_default_scalar_parameter_value(mat, name_str))
        except Exception:
            pass
        params.append(p)

    # Vector parameters
    for name in mel.get_vector_parameter_names(mat):
        name_str = str(name)
        p = {"name": name_str, "type": "vector"}
        try:
            c = mel.get_material_default_vector_parameter_value(mat, name_str)
            p["default"] = {"r": c.r, "g": c.g, "b": c.b, "a": c.a}
        except Exception:
            pass
        params.append(p)

    # Texture parameters
    for name in mel.get_texture_parameter_names(mat):
        name_str = str(name)
        p = {"name": name_str, "type": "texture"}
        try:
            tex = mel.get_material_default_texture_parameter_value(mat, name_str)
            p["default"] = str(tex.get_path_name()) if tex else None
        except Exception:
            pass
        params.append(p)

    # Static switch parameters
    for name in mel.get_static_switch_parameter_names(mat):
        name_str = str(name)
        p = {"name": name_str, "type": "static_switch"}
        try:
            p["default"] = bool(mel.get_material_default_static_switch_parameter_value(mat, name_str))
        except Exception:
            pass
        params.append(p)

    return json.dumps({"asset_path": asset_path, "parameters": params})


def scan_all_expressions(asset_path, class_filter=None):
    """Brute-force scan all expressions in a material.

    Uses find_object with ClassName_N patterns across known expression classes.
    class_filter: optional string to limit scan to classes containing this substring.
    """
    mat = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not mat:
        return json.dumps({"error": True, "message": f"Asset not found: {asset_path}"})

    if mat.get_class().get_name() != "Material":
        return json.dumps({"error": True, "message": f"Not a base Material (is {mat.get_class().get_name()}). Expression scanning only works on Materials, not Material Instances."})

    target_count = mel.get_num_material_expressions(mat)
    asset_name = _get_asset_name(asset_path)
    pkg = asset_path

    classes_to_scan = EXPRESSION_CLASSES
    if class_filter:
        cf = class_filter.lower()
        classes_to_scan = [c for c in EXPRESSION_CLASSES if cf in c.lower()]

    found = []
    for cls_short in classes_to_scan:
        cls_full = f"MaterialExpression{cls_short}"
        for i in range(200):  # safety cap
            obj_path = f"{pkg}.{asset_name}:{cls_full}_{i}"
            expr = unreal.find_object(None, obj_path)
            if not expr:
                break
            props = _get_expr_properties(expr)
            found.append({
                "name": expr.get_name(),
                "class": cls_full,
                "class_short": cls_short,
                **props,
            })
        # Early termination
        if not class_filter and len(found) >= target_count:
            break

    return json.dumps({
        "asset_path": asset_path,
        "target_count": target_count,
        "found_count": len(found),
        "expressions": found,
    })


def trace_connections(asset_path, expression_name=None):
    """Trace connections in a material graph.

    If expression_name given (e.g. 'MaterialExpressionAdd_3'), traces from that node.
    If omitted, traces from material output pins.
    """
    mat = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not mat:
        return json.dumps({"error": True, "message": f"Asset not found: {asset_path}"})

    asset_name = _get_asset_name(asset_path)

    def _trace_node(expr, depth=0, visited=None):
        if visited is None:
            visited = set()
        name = expr.get_name()
        if name in visited or depth > 20:
            return {"name": name, "class": expr.get_class().get_name(), "cycle": True}
        visited.add(name)

        node = {
            "name": name,
            "class": expr.get_class().get_name(),
        }
        connected = mel.get_inputs_for_material_expression(mat, expr)
        input_names = mel.get_material_expression_input_names(expr)
        inputs = []
        for j, c in enumerate(connected):
            pin = str(input_names[j]) if j < len(input_names) else f"input_{j}"
            if c:
                inputs.append({
                    "pin": pin,
                    "source": _trace_node(c, depth + 1, visited),
                })
            else:
                inputs.append({"pin": pin, "source": None})
        if inputs:
            node["inputs"] = inputs
        return node

    if expression_name:
        # Trace from specific expression
        obj_path = f"{asset_path}.{asset_name}:{expression_name}"
        expr = unreal.find_object(None, obj_path)
        if not expr:
            return json.dumps({"error": True, "message": f"Expression not found: {expression_name}"})
        tree = _trace_node(expr)
        return json.dumps({"asset_path": asset_path, "root": expression_name, "tree": tree})

    # Trace from material output pins
    output_props = [
        ("BaseColor", unreal.MaterialProperty.MP_BASE_COLOR),
        ("Metallic", unreal.MaterialProperty.MP_METALLIC),
        ("Specular", unreal.MaterialProperty.MP_SPECULAR),
        ("Roughness", unreal.MaterialProperty.MP_ROUGHNESS),
        ("EmissiveColor", unreal.MaterialProperty.MP_EMISSIVE_COLOR),
        ("Opacity", unreal.MaterialProperty.MP_OPACITY),
        ("OpacityMask", unreal.MaterialProperty.MP_OPACITY_MASK),
        ("Normal", unreal.MaterialProperty.MP_NORMAL),
        ("WorldPositionOffset", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET),
        ("AmbientOcclusion", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION),
        ("SubsurfaceColor", unreal.MaterialProperty.MP_SUBSURFACE_COLOR),
    ]
    outputs = []
    for label, prop in output_props:
        try:
            node = mel.get_material_property_input_node(mat, prop)
            if node:
                outputs.append({
                    "pin": label,
                    "tree": _trace_node(node),
                })
        except Exception:
            pass

    return json.dumps({"asset_path": asset_path, "root": "MaterialOutputs", "outputs": outputs})


def search_materials_in_path(base_path, query, filter_type="parameter"):
    """Search for materials by parameter name, expression type, or shading model.

    base_path: Content path to search, e.g. '/Game/Materials'
    query: Search string (case-insensitive)
    filter_type: 'parameter', 'expression', or 'shading_model'
    """
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = ar.get_assets_by_path(base_path, recursive=True)

    results = []
    query_lower = query.lower()

    for asset_data in assets:
        class_name = str(asset_data.asset_class_path.asset_name)
        if class_name not in ("Material", "MaterialInstanceConstant"):
            continue

        path = str(asset_data.package_name)
        try:
            mat = unreal.EditorAssetLibrary.load_asset(path)
            if not mat:
                continue
        except Exception:
            continue

        match_reason = None

        if filter_type == "parameter":
            all_names = []
            for fn in [mel.get_scalar_parameter_names, mel.get_vector_parameter_names,
                       mel.get_texture_parameter_names, mel.get_static_switch_parameter_names]:
                try:
                    all_names.extend([str(n) for n in fn(mat)])
                except Exception:
                    pass
            for n in all_names:
                if query_lower in n.lower():
                    match_reason = f"parameter: {n}"
                    break

        elif filter_type == "shading_model":
            try:
                sm = str(mat.get_editor_property("shading_model"))
                if query_lower in sm.lower():
                    match_reason = f"shading_model: {sm}"
            except Exception:
                pass

        elif filter_type == "expression":
            # Check if material contains expressions of a given class
            if class_name == "Material":
                asset_name = path.rsplit("/", 1)[-1]
                cls_full = f"MaterialExpression{query}"
                for i in range(5):  # quick check, not full scan
                    obj = unreal.find_object(None, f"{path}.{asset_name}:{cls_full}_{i}")
                    if obj:
                        match_reason = f"expression: {cls_full}_{i}"
                        break

        if match_reason:
            results.append({"path": path, "class": class_name, "match": match_reason})

    return json.dumps({"base_path": base_path, "query": query, "filter_type": filter_type, "results": results})
```

**Step 3: Verify the helpers package is importable (as a regular Python module, not UE)**

Run: `cd C:/Projects/unreal-material-mcp && uv run python -c "import importlib.resources; print('helpers package OK')"`
Expected: `helpers package OK`

**Step 4: Commit**

```bash
git add src/unreal_material_mcp/helpers/
git commit -m "feat: add material_helpers.py for editor-side expression scanning and tracing"
```

---

### Task 4: Server — Helper Upload + run_material_script()

**Files:**
- Create: `src/unreal_material_mcp/server.py`

**Step 1: Write test for helper upload logic**

Create `tests/__init__.py` (empty) and `tests/test_server.py`:

```python
"""Tests for MCP server tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_server():
    """Reset server state between tests."""
    from unreal_material_mcp.server import _reset_state
    _reset_state()
    yield
    _reset_state()


class TestHelperUpload:
    def test_ensure_helper_writes_file(self, tmp_path) -> None:
        from unreal_material_mcp import server

        # Point to tmp_path as project
        server._project_path = str(tmp_path)

        # Mock the bridge to accept the upload command
        mock_bridge = MagicMock()
        mock_bridge.run_command.return_value = {"success": True, "output": ""}
        server._bridge = mock_bridge

        server._ensure_helper_uploaded()

        # Should have called run_command to write the helper file
        assert mock_bridge.run_command.called
        call_args = mock_bridge.run_command.call_args[0][0]
        assert "material_helpers" in call_args

    def test_ensure_helper_skips_if_uploaded(self, tmp_path) -> None:
        from unreal_material_mcp import server

        server._project_path = str(tmp_path)
        server._helper_uploaded = True

        mock_bridge = MagicMock()
        server._bridge = mock_bridge

        server._ensure_helper_uploaded()

        # Should NOT have called run_command
        assert not mock_bridge.run_command.called
```

**Step 2: Run tests to verify they fail**

Run: `cd C:/Projects/unreal-material-mcp && uv run pytest tests/test_server.py -v`
Expected: FAIL — `server` module doesn't exist yet

**Step 3: Write `server.py` with helper upload infrastructure**

```python
"""MCP server with 5 tools for UE Material graph intelligence."""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import logging

from mcp.server.fastmcp import FastMCP

from unreal_material_mcp.config import UE_PROJECT_PATH
from unreal_material_mcp.editor_bridge import EditorBridge, EditorNotRunning

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "unreal-material",
    instructions=(
        "Material graph intelligence for Unreal Engine. "
        "Inspect material attributes, parameters, expressions, "
        "connection graphs, and search across materials."
    ),
)

_bridge: EditorBridge | None = None
_project_path: str = UE_PROJECT_PATH
_helper_uploaded: bool = False
_helper_hash: str = ""


def _reset_state() -> None:
    """Reset all singletons (for testing)."""
    global _bridge, _project_path, _helper_uploaded, _helper_hash
    if _bridge:
        _bridge.disconnect()
    _bridge = None
    _project_path = ""
    _helper_uploaded = False
    _helper_hash = ""


def _get_bridge() -> EditorBridge:
    """Lazy-init the editor bridge."""
    global _bridge
    if _bridge is not None:
        return _bridge
    _bridge = EditorBridge(auto_connect=False)
    return _bridge


def _get_helper_source() -> str:
    """Read the material_helpers.py source from the installed package."""
    ref = importlib.resources.files("unreal_material_mcp") / "helpers" / "material_helpers.py"
    return ref.read_text(encoding="utf-8")


def _ensure_helper_uploaded() -> None:
    """Upload material_helpers.py to the editor's Saved/ directory if needed."""
    global _helper_uploaded, _helper_hash

    if _helper_uploaded:
        return

    bridge = _get_bridge()
    source = _get_helper_source()
    new_hash = hashlib.md5(source.encode()).hexdigest()[:12]

    if new_hash == _helper_hash:
        _helper_uploaded = True
        return

    # Write helper to Saved/MaterialMCP/material_helpers.py via editor Python
    saved_dir = _project_path.replace("\\", "/") + "/Saved/MaterialMCP"
    escaped_source = source.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")

    upload_cmd = (
        "import os\n"
        f"os.makedirs('{saved_dir}', exist_ok=True)\n"
        f"with open('{saved_dir}/material_helpers.py', 'w') as f:\n"
        f"    f.write('{escaped_source}')\n"
        "print('OK')"
    )

    result = bridge.run_command(upload_cmd, exec_mode="ExecuteFile")
    if not result.get("success"):
        raise RuntimeError(f"Failed to upload helper: {result.get('result', 'unknown error')}")

    _helper_hash = new_hash
    _helper_uploaded = True


def _escape_py_string(s: str) -> str:
    """Escape a string for safe interpolation into a Python string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'").replace("\n", "\\n")


def _run_material_script(script_body: str) -> dict:
    """Upload helper if needed, then run a short script that imports it.

    script_body should call material_helpers functions and end with:
        print(result_json)

    Returns parsed JSON dict from the script output.
    """
    _ensure_helper_uploaded()
    bridge = _get_bridge()

    saved_dir = _project_path.replace("\\", "/") + "/Saved/MaterialMCP"
    full_script = (
        "import sys, json\n"
        f"if '{saved_dir}' not in sys.path:\n"
        f"    sys.path.insert(0, '{saved_dir}')\n"
        "import importlib\n"
        "import material_helpers\n"
        "importlib.reload(material_helpers)\n"
        + script_body
    )

    result = bridge.run_command(full_script, exec_mode="ExecuteFile")
    if not result.get("success"):
        return {"error": True, "message": result.get("result", "Command failed")}

    # Parse output — same pattern as blueprint server
    raw_output = result.get("output", "")
    if isinstance(raw_output, list):
        parts = []
        for item in raw_output:
            if isinstance(item, dict):
                parts.append(item.get("output", str(item)))
            else:
                parts.append(str(item))
        output = "\n".join(parts).strip()
    else:
        output = str(raw_output).strip()

    if not output:
        raw_result = result.get("result", "")
        output = str(raw_result).strip()

    # Find JSON in output (skip any UE warnings)
    json_start = output.find("{")
    if json_start > 0:
        output = output[json_start:]

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {"error": True, "message": f"Invalid JSON from editor: {output[:500]}"}


def _format_error(data: dict) -> str | None:
    """Return error message if data is an error response, else None."""
    if data.get("error"):
        return f"Error: {data.get('message', 'Unknown error')}"
    return None


# -- Tools (5) ---------------------------------------------------------------


@mcp.tool()
def get_material_info(asset_path: str) -> str:
    """Get material attributes: blend mode, shading model, domain, usage flags, expression count.

    asset_path: Full asset path, e.g. '/Game/Materials/M_Base'
    """
    try:
        data = _run_material_script(
            f"print(material_helpers.get_material_info('{_escape_py_string(asset_path)}'))"
        )
    except EditorNotRunning as e:
        return f"Editor not available: {e}"
    except RuntimeError as e:
        return str(e)

    err = _format_error(data)
    if err:
        return err

    lines = [f"Material: {data.get('asset_path', '')}"]
    lines.append(f"Class: {data.get('class', '')}")

    if data.get("parent"):
        lines.append(f"Parent: {data['parent']}")

    for key in ["blend_mode", "shading_model", "material_domain", "two_sided", "expression_count"]:
        if key in data:
            label = key.replace("_", " ").title()
            lines.append(f"{label}: {data[key]}")

    flags = data.get("usage_flags", {})
    if flags:
        lines.append("")
        lines.append("Usage flags:")
        for flag in sorted(flags.keys()):
            clean = flag.replace("b_used_with_", "").replace("_", " ").title()
            lines.append(f"  {clean}")

    return "\n".join(lines)


@mcp.tool()
def get_material_parameters(asset_path: str) -> str:
    """Get all material parameters (scalar, vector, texture, static switch) with types and defaults.

    asset_path: Full asset path, e.g. '/Game/Materials/M_Base'
    """
    try:
        data = _run_material_script(
            f"print(material_helpers.get_all_parameters('{_escape_py_string(asset_path)}'))"
        )
    except EditorNotRunning as e:
        return f"Editor not available: {e}"
    except RuntimeError as e:
        return str(e)

    err = _format_error(data)
    if err:
        return err

    params = data.get("parameters", [])
    if not params:
        return f"No parameters found in {asset_path}"

    lines = [f"Parameters for {data.get('asset_path', '')}:", ""]

    # Group by type
    by_type: dict[str, list] = {}
    for p in params:
        by_type.setdefault(p["type"], []).append(p)

    for type_name in ["scalar", "vector", "texture", "static_switch"]:
        group = by_type.get(type_name, [])
        if not group:
            continue
        lines.append(f"  [{type_name.replace('_', ' ').title()}]")
        for p in group:
            default = p.get("default", "?")
            if isinstance(default, dict):
                default = f"({default.get('r', 0):.2f}, {default.get('g', 0):.2f}, {default.get('b', 0):.2f}, {default.get('a', 0):.2f})"
            group_name = f" ({p['group']})" if p.get("group") else ""
            lines.append(f"    {p['name']} = {default}{group_name}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def get_material_expressions(asset_path: str, class_filter: str = "") -> str:
    """List all expressions in a material with types, names, positions, and key properties.

    asset_path: Full asset path to a Material (not MI), e.g. '/Game/Materials/M_Base'
    class_filter: Optional filter — only scan classes containing this string (e.g. 'Parameter', 'Custom')
    """
    try:
        filter_arg = f", class_filter='{_escape_py_string(class_filter)}'" if class_filter else ""
        data = _run_material_script(
            f"print(material_helpers.scan_all_expressions('{_escape_py_string(asset_path)}'{filter_arg}))"
        )
    except EditorNotRunning as e:
        return f"Editor not available: {e}"
    except RuntimeError as e:
        return str(e)

    err = _format_error(data)
    if err:
        return err

    exprs = data.get("expressions", [])
    target = data.get("target_count", "?")
    found = data.get("found_count", len(exprs))

    lines = [
        f"Expressions in {data.get('asset_path', '')}:",
        f"Found {found} of {target} expressions",
        "",
    ]

    # Group by class_short
    by_class: dict[str, list] = {}
    for e in exprs:
        by_class.setdefault(e.get("class_short", "Unknown"), []).append(e)

    for cls_short in sorted(by_class.keys()):
        group = by_class[cls_short]
        lines.append(f"  [{cls_short}] ({len(group)})")
        for e in group:
            pos = f"({e.get('x', '?')}, {e.get('y', '?')})"
            extra = ""
            if e.get("parameter_name"):
                extra = f' "{e["parameter_name"]}"'
            elif e.get("description"):
                extra = f' "{e["description"]}"'
            elif e.get("text"):
                extra = f' "{e["text"][:60]}"'
            elif e.get("value") is not None:
                extra = f" = {e['value']}"
            lines.append(f"    {e['name']} {pos}{extra}")
        lines.append("")

    if found < target:
        lines.append(f"Note: {target - found} expressions not found — may be unlisted class types.")

    return "\n".join(lines)


@mcp.tool()
def trace_material_connections(asset_path: str, expression_name: str = "") -> str:
    """Trace the connection graph of a material.

    asset_path: Full asset path, e.g. '/Game/Materials/M_Base'
    expression_name: Optional expression name (e.g. 'MaterialExpressionAdd_3').
        If given, traces connections into that node recursively.
        If omitted, traces from material output pins (BaseColor, Normal, etc.).
    """
    try:
        expr_arg = f", expression_name='{_escape_py_string(expression_name)}'" if expression_name else ""
        data = _run_material_script(
            f"print(material_helpers.trace_connections('{_escape_py_string(asset_path)}'{expr_arg}))"
        )
    except EditorNotRunning as e:
        return f"Editor not available: {e}"
    except RuntimeError as e:
        return str(e)

    err = _format_error(data)
    if err:
        return err

    lines = [f"Connections for {data.get('asset_path', '')}:"]
    lines.append(f"Root: {data.get('root', '?')}")
    lines.append("")

    def _format_tree(node: dict, indent: int = 0) -> None:
        prefix = "  " * indent
        name = node.get("name", "?")
        cls = node.get("class", "?").replace("MaterialExpression", "")
        cycle = " [CYCLE]" if node.get("cycle") else ""
        lines.append(f"{prefix}{name} ({cls}){cycle}")
        for inp in node.get("inputs", []):
            pin = inp.get("pin", "?")
            src = inp.get("source")
            if src:
                lines.append(f"{prefix}  [{pin}]:")
                _format_tree(src, indent + 2)
            else:
                lines.append(f"{prefix}  [{pin}]: (unconnected)")

    if "tree" in data:
        _format_tree(data["tree"])
    elif "outputs" in data:
        for out in data["outputs"]:
            lines.append(f"--- {out['pin']} ---")
            _format_tree(out["tree"], 1)
            lines.append("")

    return "\n".join(lines)


@mcp.tool()
def search_materials(path: str, query: str, filter_type: str = "parameter") -> str:
    """Search for materials in a content path by parameter name, expression type, or shading model.

    path: Content path to search, e.g. '/Game/Materials' or '/Game'
    query: Search string (case-insensitive for parameter/shading_model, class name for expression e.g. 'Custom')
    filter_type: 'parameter' (default), 'expression', or 'shading_model'
    """
    try:
        data = _run_material_script(
            f"print(material_helpers.search_materials_in_path("
            f"'{_escape_py_string(path)}', "
            f"'{_escape_py_string(query)}', "
            f"'{_escape_py_string(filter_type)}'))"
        )
    except EditorNotRunning as e:
        return f"Editor not available: {e}"
    except RuntimeError as e:
        return str(e)

    err = _format_error(data)
    if err:
        return err

    results = data.get("results", [])
    if not results:
        return f"No materials matching '{query}' ({filter_type}) in {path}"

    lines = [
        f"Found {len(results)} materials matching '{query}' ({filter_type}) in {path}:",
        "",
    ]
    for r in results:
        lines.append(f"  {r['path']} ({r['class']})")
        lines.append(f"    Match: {r['match']}")

    return "\n".join(lines)


# -- Entry point -----------------------------------------------------------


def main() -> None:
    """Run the MCP server."""
    mcp.run()
```

**Step 4: Run tests to verify they pass**

Run: `cd C:/Projects/unreal-material-mcp && uv run pytest tests/test_server.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/unreal_material_mcp/server.py tests/
git commit -m "feat: server with helper upload, run_material_script, and 5 tool definitions"
```

---

### Task 5: Tests — Tool Output Formatting

**Files:**
- Modify: `tests/test_server.py`

**Step 1: Add tests for all 5 tools**

Append to `tests/test_server.py`:

```python
def _make_bridge_mock(return_data: dict) -> MagicMock:
    """Create a mock bridge that returns JSON for material_helpers calls."""
    mock = MagicMock()
    # First call: helper upload (returns OK)
    # Second call: actual tool script (returns JSON)
    mock.run_command.side_effect = [
        {"success": True, "output": "OK"},  # upload
        {"success": True, "output": json.dumps(return_data)},  # tool
    ]
    return mock


def _setup_with_mock(return_data: dict):
    """Set up server with a mock bridge returning given data."""
    from unreal_material_mcp import server
    server._project_path = "/tmp/TestProject"
    server._helper_uploaded = False
    server._bridge = _make_bridge_mock(return_data)


class TestGetMaterialInfo:
    def test_formats_material_info(self) -> None:
        _setup_with_mock({
            "asset_path": "/Game/M_Test",
            "class": "Material",
            "blend_mode": "BLEND_Opaque",
            "shading_model": "MSM_DEFAULT_LIT",
            "material_domain": "MD_SURFACE",
            "two_sided": False,
            "expression_count": 12,
        })
        from unreal_material_mcp.server import get_material_info
        result = get_material_info("/Game/M_Test")
        assert "Material: /Game/M_Test" in result
        assert "BLEND_Opaque" in result
        assert "MSM_DEFAULT_LIT" in result
        assert "12" in result

    def test_shows_usage_flags(self) -> None:
        _setup_with_mock({
            "asset_path": "/Game/M_Test",
            "class": "Material",
            "usage_flags": {"b_used_with_skeletal_mesh": True},
        })
        from unreal_material_mcp.server import get_material_info
        result = get_material_info("/Game/M_Test")
        assert "Skeletal Mesh" in result

    def test_error_response(self) -> None:
        _setup_with_mock({"error": True, "message": "Asset not found: /Game/Bad"})
        from unreal_material_mcp.server import get_material_info
        result = get_material_info("/Game/Bad")
        assert "Error" in result
        assert "Asset not found" in result


class TestGetMaterialParameters:
    def test_formats_parameters(self) -> None:
        _setup_with_mock({
            "asset_path": "/Game/M_Test",
            "parameters": [
                {"name": "Roughness", "type": "scalar", "default": 0.5},
                {"name": "BaseColor", "type": "vector", "default": {"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0}},
                {"name": "Diffuse", "type": "texture", "default": "/Game/T_Diff"},
                {"name": "UseBump", "type": "static_switch", "default": True},
            ],
        })
        from unreal_material_mcp.server import get_material_parameters
        result = get_material_parameters("/Game/M_Test")
        assert "Roughness = 0.5" in result
        assert "BaseColor" in result
        assert "Diffuse" in result
        assert "UseBump = True" in result

    def test_no_parameters(self) -> None:
        _setup_with_mock({"asset_path": "/Game/M_Test", "parameters": []})
        from unreal_material_mcp.server import get_material_parameters
        result = get_material_parameters("/Game/M_Test")
        assert "No parameters" in result


class TestGetMaterialExpressions:
    def test_formats_expressions(self) -> None:
        _setup_with_mock({
            "asset_path": "/Game/M_Test",
            "target_count": 3,
            "found_count": 3,
            "expressions": [
                {"name": "MaterialExpressionAdd_0", "class": "MaterialExpressionAdd", "class_short": "Add", "x": -300, "y": -100},
                {"name": "MaterialExpressionScalarParameter_0", "class": "MaterialExpressionScalarParameter", "class_short": "ScalarParameter", "x": -600, "y": -100, "parameter_name": "Roughness"},
                {"name": "MaterialExpressionConstant_0", "class": "MaterialExpressionConstant", "class_short": "Constant", "x": -600, "y": 0, "value": 1.0},
            ],
        })
        from unreal_material_mcp.server import get_material_expressions
        result = get_material_expressions("/Game/M_Test")
        assert "Found 3 of 3" in result
        assert "[Add]" in result
        assert '"Roughness"' in result
        assert "= 1.0" in result

    def test_missing_expressions_note(self) -> None:
        _setup_with_mock({
            "asset_path": "/Game/M_Test",
            "target_count": 10,
            "found_count": 7,
            "expressions": [{"name": "X_0", "class": "X", "class_short": "X"}] * 7,
        })
        from unreal_material_mcp.server import get_material_expressions
        result = get_material_expressions("/Game/M_Test")
        assert "3 expressions not found" in result


class TestTraceMaterialConnections:
    def test_formats_output_trace(self) -> None:
        _setup_with_mock({
            "asset_path": "/Game/M_Test",
            "root": "MaterialOutputs",
            "outputs": [{
                "pin": "BaseColor",
                "tree": {
                    "name": "MaterialExpressionMultiply_0",
                    "class": "MaterialExpressionMultiply",
                    "inputs": [
                        {"pin": "A", "source": {"name": "MaterialExpressionTextureSampleParameter2D_0", "class": "MaterialExpressionTextureSampleParameter2D"}},
                        {"pin": "B", "source": None},
                    ],
                },
            }],
        })
        from unreal_material_mcp.server import trace_material_connections
        result = trace_material_connections("/Game/M_Test")
        assert "BaseColor" in result
        assert "Multiply" in result
        assert "TextureSampleParameter2D" in result
        assert "(unconnected)" in result

    def test_formats_node_trace(self) -> None:
        _setup_with_mock({
            "asset_path": "/Game/M_Test",
            "root": "MaterialExpressionAdd_0",
            "tree": {
                "name": "MaterialExpressionAdd_0",
                "class": "MaterialExpressionAdd",
                "inputs": [
                    {"pin": "A", "source": {"name": "MaterialExpressionConstant_0", "class": "MaterialExpressionConstant"}},
                    {"pin": "B", "source": {"name": "MaterialExpressionConstant_1", "class": "MaterialExpressionConstant"}},
                ],
            },
        })
        from unreal_material_mcp.server import trace_material_connections
        result = trace_material_connections("/Game/M_Test", "MaterialExpressionAdd_0")
        assert "Add_0" in result
        assert "Constant_0" in result
        assert "Constant_1" in result


class TestSearchMaterials:
    def test_formats_results(self) -> None:
        _setup_with_mock({
            "base_path": "/Game",
            "query": "Roughness",
            "filter_type": "parameter",
            "results": [
                {"path": "/Game/M_Stone", "class": "Material", "match": "parameter: Roughness"},
                {"path": "/Game/MI_Stone_Wet", "class": "MaterialInstanceConstant", "match": "parameter: Roughness"},
            ],
        })
        from unreal_material_mcp.server import search_materials
        result = search_materials("/Game", "Roughness")
        assert "Found 2" in result
        assert "M_Stone" in result
        assert "MI_Stone_Wet" in result

    def test_no_results(self) -> None:
        _setup_with_mock({
            "base_path": "/Game",
            "query": "NonExistent",
            "filter_type": "parameter",
            "results": [],
        })
        from unreal_material_mcp.server import search_materials
        result = search_materials("/Game", "NonExistent")
        assert "No materials matching" in result
```

**Step 2: Run all tests**

Run: `cd C:/Projects/unreal-material-mcp && uv run pytest tests/ -v`
Expected: ALL PASS (14 tests: 2 helper upload + 12 tool formatting)

**Step 3: Commit**

```bash
git add tests/
git commit -m "test: add 14 tests for helper upload and all 5 tool output formatting"
```

---

### Task 6: CLAUDE.md

**Files:**
- Create: `CLAUDE.md`

**Step 1: Write CLAUDE.md**

```markdown
# CLAUDE.md — unreal-material-mcp

## Project Overview

**unreal-material-mcp** — Material graph intelligence for Unreal Engine AI development.

An MCP server that inspects UE material graphs via the editor Python bridge. Read material attributes, parameters, expression nodes, connection graphs, and search across materials.

**Complements** (does not replace):
- `unreal-source-mcp` — Engine-level source intelligence
- `unreal-project-mcp` — Project-level source intelligence
- `unreal-editor-mcp` — Build diagnostics and editor log tools
- `unreal-blueprint-mcp` — Blueprint graph reading
- `unreal-config-mcp` — Config/INI intelligence

**We provide:** Material graph inspection — expressions, connections, parameters, attributes.

## Tech Stack

- **Language:** Python 3.11+
- **MCP SDK:** `mcp` Python package (FastMCP)
- **Distribution:** PyPI via `uvx unreal-material-mcp`
- **Package manager:** `uv` (for dev and build)

## Project Structure

    unreal-material-mcp/
    ├── pyproject.toml
    ├── CLAUDE.md
    ├── src/
    │   └── unreal_material_mcp/
    │       ├── __init__.py              # Version
    │       ├── __main__.py              # CLI entry point
    │       ├── config.py                # UE_PROJECT_PATH, port config
    │       ├── server.py                # FastMCP + 5 tool definitions
    │       ├── editor_bridge.py         # UE remote execution protocol client
    │       └── helpers/
    │           └── material_helpers.py  # Uploaded to editor, runs in-process
    └── tests/
        └── test_server.py              # Mocked bridge tests

## Build & Run

```bash
uv sync                                    # Install deps
uv run pytest tests/ -v                    # Run tests
uv run python -m unreal_material_mcp       # Run MCP server
```

## MCP Configuration (for Claude Code)

```json
{
  "mcpServers": {
    "unreal-material": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/tumourlove/unreal-material-mcp.git", "unreal-material-mcp"],
      "env": {
        "UE_PROJECT_PATH": "D:/Unreal Projects/Leviathan"
      }
    }
  }
}
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `UE_PROJECT_PATH` | Path to UE project root (contains .uproject) — required |
| `UE_EDITOR_PYTHON_PORT` | TCP port for command connection (default: 6776) |
| `UE_MULTICAST_GROUP` | UDP multicast group for discovery (default: 239.0.0.1) |
| `UE_MULTICAST_PORT` | UDP multicast port (default: 6766) |
| `UE_MULTICAST_BIND` | Multicast bind address (default: 127.0.0.1) |

## MCP Tools (5)

| Tool | Purpose |
|------|---------|
| `get_material_info` | Material attributes: blend mode, shading model, domain, usage flags, expression count |
| `get_material_parameters` | All parameters (scalar, vector, texture, static switch) with defaults and groups |
| `get_material_expressions` | All expressions with types, names, positions, key properties. Optional class filter |
| `trace_material_connections` | Connection graph from a specific node or from material output pins |
| `search_materials` | Find materials by parameter name, expression type, or shading model |

## Architecture Notes

- **Helper module strategy** — `material_helpers.py` is uploaded to `{project}/Saved/MaterialMCP/` on first tool call. Tools send short scripts that import it. Version hash skips re-upload if unchanged.
- **Expression discovery** — brute-force scan using `find_object` with `ClassName_N` patterns across ~35+ known expression classes. `get_num_material_expressions()` provides target count for early termination.
- **Editor bridge** — UE remote execution protocol: UDP multicast discovery → TCP command connection. Shared pattern across all sister servers.
- **No expression iteration API** — UE 5.7 has no `get_material_expression(mat, index)`. The `find_object` scan is the only way.
- **`connect_material_expressions` takes 4 args** — `(from, out_pin, to, in_pin)`. NO material argument. #1 gotcha.

## Coding Conventions

- **Lazy singletons** — `_get_bridge()` inits on first call, stored in module global
- **`_reset_state()`** — every module with singletons exposes this for test teardown
- **Mock-based testing** — tests mock EditorBridge; no real editor needed
- **Formatted string returns** — all tools return human-readable multi-line strings, not raw JSON
- Follow standard Python conventions: snake_case, type hints, docstrings on public functions
- Use `logging` module, not print statements
- Keep dependencies minimal — just `mcp>=1.0.0`
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md project guide"
```

---

### Task 7: Live Validation with Editor

**Prerequisites:** UE editor running with Leviathan project open.

**Step 1: Run the server and test manually with a known material**

Run: `cd C:/Projects/unreal-material-mcp && UE_PROJECT_PATH="D:/Unreal Projects/Leviathan" uv run python -m unreal_material_mcp`

**Step 2: Test each tool against a real material**

Use a material you know exists in the project (e.g. from the DrawCallReducer plugin or main content). If any tool returns errors or unexpected results, fix the helper module accordingly.

Key things to validate:
- Bridge connects to the editor
- Helper uploads successfully
- `get_material_info` returns correct attributes
- `get_material_parameters` lists all parameter types
- `get_material_expressions` finds expressions (check found_count vs target_count)
- `trace_material_connections` produces a valid tree
- `search_materials` finds materials by parameter name

**Step 3: Fix any issues found and commit**

```bash
git add -A
git commit -m "fix: corrections from live editor validation"
```

---

### Summary

| Task | Description | Tests |
|------|-------------|-------|
| 1 | Project scaffolding | import check |
| 2 | Editor bridge | import check |
| 3 | material_helpers.py | — (tested via Task 5) |
| 4 | Server + helper upload + 5 tools | 2 upload tests |
| 5 | Tool formatting tests | 12 tests |
| 6 | CLAUDE.md | — |
| 7 | Live editor validation | manual |

Total: 7 tasks, 14 automated tests, ~7 commits.
