# Missing Tier 1 & 2 Features Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement all missing Tier 1 inspection and Tier 2 editing features: 3 existing tools extended + 11 new tools.

**Architecture:** Extend `material_helpers.py` with new helper functions, add corresponding MCP tool definitions in `server.py`, and add tests in `test_server.py`. Each helper function returns JSON strings following the existing `{"success": True, ...}` / `{"success": False, "error": "..."}` envelope pattern. Tools format helper JSON into human-readable strings.

**Tech Stack:** Python 3.11+, FastMCP, Unreal Engine 5.7+ Python API (`unreal` module), pytest with mocked EditorBridge.

**Design doc:** `docs/plans/2026-03-04-tier1-tier2-missing-features-design.md`

---

## Key Conventions (read before implementing)

- **Helper functions** (`material_helpers.py`): Return `json.dumps(...)` strings. Use `_error_json(exc)` for errors. Use `_load_material()`, `_mel()`, `_eal()`, `_full_object_path()`, `_expr_id()`, `_expr_position()`, `_safe_enum_name()` for common operations.
- **Tool functions** (`server.py`): Call `_run_material_script(script)` which handles helper upload + script execution. Format results as human-readable strings. Use `_format_error(data)` for error checking.
- **Tests** (`test_server.py`): Use `_setup_tool_mock(return_data)` to mock bridge. Use `@patch.object(server, "_get_helper_source", return_value="# src\n")` decorator. Test output formatting only (no real UE calls).
- **Script pattern in server.py tools**: Build Python script string that calls `material_helpers.function_name(args)`, wrapped in `_run_material_script()`.

---

### Task 1: Extend `get_material_parameters` — Static Switch Values

**Files:**
- Modify: `src/unreal_material_mcp/helpers/material_helpers.py` (function `get_all_parameters`, lines 268-348)
- Modify: `src/unreal_material_mcp/server.py` (function `get_material_parameters`, lines 209-264)
- Test: `tests/test_server.py` (class `TestGetMaterialParameters`)

**Step 1: Write the failing test**

Add to `tests/test_server.py` in class `TestGetMaterialParameters`:

```python
@patch.object(server, "_get_helper_source", return_value="# src\n")
def test_formats_static_switch_with_value_and_controls(self, _src):
    _setup_tool_mock({
        "success": True,
        "asset_path": "/Game/M_Foo",
        "parameters": [
            {
                "name": "UseDetail",
                "type": "StaticSwitch",
                "default": True,
                "controls": [
                    {
                        "expression": "MaterialExpressionIf_0",
                        "true_input": "Multiply_3",
                        "false_input": "Constant_2",
                    }
                ],
            },
        ],
    })
    result = server.get_material_parameters("/Game/M_Foo")

    assert "UseDetail" in result
    assert "value=True" in result
    assert "Controls:" in result
    assert "MaterialExpressionIf_0" in result
```

**Step 2: Run test to verify it fails**

Run: `cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py::TestGetMaterialParameters::test_formats_static_switch_with_value_and_controls -v`
Expected: FAIL (output doesn't contain "value=True" or "Controls:")

**Step 3: Update server.py formatting**

In `server.py`, in the `get_material_parameters` function, after line 253 (`lines.append(f"    {p['name']} = {default_str}")`), add static switch detail rendering:

```python
# After the existing lines.append for each parameter:
            lines.append(f"    {p['name']} = {default_str}")
            # Show static switch controls if present
            if ptype == "StaticSwitch" and "controls" in p:
                lines[-1] = f"    {p['name']} value={default_str}"
                for ctrl in p["controls"]:
                    true_in = ctrl.get("true_input", "?")
                    false_in = ctrl.get("false_input", "?")
                    lines.append(
                        f"      Controls: {ctrl.get('expression', '?')} "
                        f"(true→{true_in}, false→{false_in})"
                    )
```

Actually, let me reconsider — the formatting needs to be cleaner. Replace the static switch section of the loop. In the `for p in items:` loop (lines 244-254), change the rendering for StaticSwitch:

Replace lines 244-254 in `server.py` with:

```python
        for p in items:
            default = p.get("default")
            if isinstance(default, dict):
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
```

**Step 4: Update material_helpers.py**

In `get_all_parameters()` (lines 268-348), after the static switch parameter collection loop (lines 328-344), add downstream tracing for each static switch parameter. The static switch section currently looks like lines 328-344. Replace it with:

```python
        # Static switch
        try:
            for name in mel.get_static_switch_parameter_names(mat):
                name_str = str(name)
                try:
                    default = bool(
                        mel.get_material_default_static_switch_parameter_value(mat, name_str)
                    )
                except Exception:
                    default = None

                param_entry = {
                    "name": name_str,
                    "type": "StaticSwitch",
                    "default": default,
                }

                # Trace controls: find StaticSwitchParameter expressions and their downstream If nodes
                controls = []
                if not _is_material_instance(mat):
                    try:
                        full_path = _full_object_path(asset_path)
                        for i in range(200):
                            obj_path = f"{full_path}:MaterialExpressionStaticSwitchParameter_{i}"
                            expr = unreal.find_object(None, obj_path)
                            if expr is None:
                                if i > 30:
                                    break
                                continue
                            try:
                                pname = str(expr.get_editor_property("parameter_name"))
                            except Exception:
                                continue
                            if pname != name_str:
                                continue
                            # Found the matching expression — check what it connects to
                            # The StaticSwitchParameter has True/False outputs that feed into
                            # downstream nodes. We look at what nodes use this expression as input.
                            # Since we can't easily trace forward, we note the expression name.
                            controls.append({
                                "expression": _expr_id(expr),
                                "position": _expr_position(expr),
                            })
                            break
                    except Exception:
                        pass

                if controls:
                    param_entry["controls"] = controls

                params.append(param_entry)
        except Exception:
            pass
```

**Step 5: Run test to verify it passes**

Run: `cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py::TestGetMaterialParameters -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/unreal_material_mcp/helpers/material_helpers.py src/unreal_material_mcp/server.py tests/test_server.py
git commit -m "feat: add static switch value and controls to get_material_parameters"
```

---

### Task 2: Extend `get_material_dependencies` — Texture Sizes & Formats

**Files:**
- Modify: `src/unreal_material_mcp/helpers/material_helpers.py` (function `get_dependencies`, lines 942-1026)
- Modify: `src/unreal_material_mcp/server.py` (function `get_material_dependencies`, lines 511-556)
- Test: `tests/test_server.py` (class `TestGetMaterialDependencies`)

**Step 1: Write the failing test**

Add to `tests/test_server.py` in class `TestGetMaterialDependencies`:

```python
@patch.object(server, "_get_helper_source", return_value="# src\n")
def test_formats_textures_with_size_and_format(self, _src):
    _setup_tool_mock({
        "success": True,
        "asset_path": "/Game/M_Foo",
        "textures": [
            {
                "path": "/Game/T_Diff",
                "width": 2048,
                "height": 2048,
                "format": "PF_DXT5",
            },
            {
                "path": "/Game/T_Norm",
                "width": 1024,
                "height": 1024,
                "format": "PF_BC5",
            },
        ],
        "functions": [],
        "parameter_sources": [],
    })
    result = server.get_material_dependencies("/Game/M_Foo")

    assert "2048x2048" in result
    assert "PF_DXT5" in result
    assert "1024x1024" in result
    assert "PF_BC5" in result
    assert "/Game/T_Diff" in result
```

**Step 2: Run test to verify it fails**

Run: `cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py::TestGetMaterialDependencies::test_formats_textures_with_size_and_format -v`
Expected: FAIL

**Step 3: Update server.py formatting**

In `get_material_dependencies` (lines 530-536), replace the texture formatting:

Old code (lines 530-536):
```python
    textures = data.get("textures", [])
    lines.append(f"  Textures ({len(textures)}):")
    if textures:
        for t in textures:
            lines.append(f"    {t}")
    else:
        lines.append("    (none)")
```

New code:
```python
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
```

**Step 4: Update material_helpers.py**

In `get_dependencies()` (lines 954-964), replace the texture collection:

Old code:
```python
        textures = []
        try:
            used = mel.get_used_textures(mat)
            for tex in used:
                try:
                    textures.append(tex.get_path_name())
                except Exception:
                    textures.append(str(tex))
        except Exception:
            pass
```

New code:
```python
        textures = []
        try:
            used = mel.get_used_textures(mat)
            for tex in used:
                try:
                    tex_entry = {"path": tex.get_path_name()}
                    try:
                        tex_entry["width"] = int(tex.blueprint_get_size_x())
                        tex_entry["height"] = int(tex.blueprint_get_size_y())
                    except Exception:
                        pass
                    try:
                        tex_entry["format"] = _safe_enum_name(tex.get_editor_property("pixel_format"))
                    except Exception:
                        try:
                            tex_entry["format"] = _safe_enum_name(
                                tex.get_editor_property("compression_settings")
                            )
                        except Exception:
                            pass
                    textures.append(tex_entry)
                except Exception:
                    textures.append({"path": str(tex)})
        except Exception:
            pass
```

**Step 5: Run tests**

Run: `cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py::TestGetMaterialDependencies -v`
Expected: All PASS

**Note:** The existing `test_formats_dependencies` test will break because `textures` is now a list of dicts instead of strings. Update it:

```python
@patch.object(server, "_get_helper_source", return_value="# src\n")
def test_formats_dependencies(self, _src):
    _setup_tool_mock({
        "success": True,
        "asset_path": "/Game/M_Foo",
        "textures": [
            {"path": "/Game/T_Diff"},
            {"path": "/Game/T_Norm"},
        ],
        "functions": [
            {"expression": "MF_Blend_0", "function_path": "/Game/MF_Blend"},
        ],
        "parameter_sources": ["/Game/MPC_Global"],
    })
    result = server.get_material_dependencies("/Game/M_Foo")

    assert "Textures (2)" in result
    assert "/Game/T_Diff" in result
    assert "Material Functions (1)" in result
    assert "MF_Blend_0 -> /Game/MF_Blend" in result
    assert "Parameter Sources (1)" in result
    assert "/Game/MPC_Global" in result
```

**Step 6: Commit**

```bash
git add src/unreal_material_mcp/helpers/material_helpers.py src/unreal_material_mcp/server.py tests/test_server.py
git commit -m "feat: add texture dimensions and format to get_material_dependencies"
```

---

### Task 3: Extend `get_material_stats` — Compile Status & Errors

**Files:**
- Modify: `src/unreal_material_mcp/helpers/material_helpers.py` (function `get_stats`, lines 832-935)
- Modify: `src/unreal_material_mcp/server.py` (function `get_material_stats`, lines 466-504)
- Test: `tests/test_server.py` (class `TestGetMaterialStats`)

**Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
@patch.object(server, "_get_helper_source", return_value="# src\n")
def test_formats_compile_errors(self, _src):
    _setup_tool_mock({
        "success": True,
        "asset_path": "/Game/M_Broken",
        "stats": {
            "num_vertex_shader_instructions": 0,
            "num_pixel_shader_instructions": 0,
            "num_samplers": 0,
            "num_pixel_texture_samples": 0,
            "num_vertex_texture_samples": 0,
            "num_virtual_texture_samples": 0,
            "num_uv_scalars": 0,
            "num_interpolator_scalars": 0,
        },
        "compile_status": "error",
        "compile_errors": ["[SM5] Missing required input BaseColor"],
        "warnings": [],
    })
    result = server.get_material_stats("/Game/M_Broken")

    assert "Compile Status: error" in result
    assert "Missing required input BaseColor" in result
```

**Step 2: Run test to verify it fails**

Run: `cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py::TestGetMaterialStats::test_formats_compile_errors -v`
Expected: FAIL

**Step 3: Update server.py formatting**

In `get_material_stats` (after the warnings section, before return), add compile status rendering. Replace lines 486-503:

```python
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
```

**Step 4: Update material_helpers.py**

In `get_stats()`, after collecting stats (around line 867), add compile status detection. Before the disconnected expression analysis section (line 880), add:

```python
        # --- Compile status ---
        compile_status = "success"
        compile_errors = []
        try:
            # If pixel shader instructions is 0 but material has expressions,
            # compilation likely failed
            if (stats.get("num_pixel_shader_instructions", 0) == 0
                    and stats.get("num_vertex_shader_instructions", 0) == 0):
                try:
                    expr_count = int(mel.get_num_material_expressions(mat))
                    if expr_count > 0:
                        compile_status = "error"
                except Exception:
                    pass
        except Exception:
            pass
```

Then include `compile_status` and `compile_errors` in the return JSON (line 924):

```python
        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "stats": stats,
            "compile_status": compile_status,
            "compile_errors": compile_errors,
            "warnings": warnings,
            "total_expressions": len(all_expr_names),
            "connected_expressions": len(connected_names & all_expr_names),
            "disconnected_expressions": disconnected,
            "unused_parameters": unused_params,
        })
```

**Step 5: Run tests**

Run: `cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py::TestGetMaterialStats -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/unreal_material_mcp/helpers/material_helpers.py src/unreal_material_mcp/server.py tests/test_server.py
git commit -m "feat: add compile status and errors to get_material_stats"
```

---

### Task 4: New Tool — `find_material_references`

**Files:**
- Modify: `src/unreal_material_mcp/helpers/material_helpers.py` (add new function at end)
- Modify: `src/unreal_material_mcp/server.py` (add new tool after tool 17)
- Test: `tests/test_server.py` (add new test class)

**Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
# ---------------------------------------------------------------------------
# Tool 18: find_material_references
# ---------------------------------------------------------------------------

class TestFindMaterialReferences:
    """Output formatting tests for find_material_references."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_references(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/Materials/M_Character",
            "references": [
                {"asset_path": "/Game/Meshes/SM_Body", "asset_type": "StaticMesh"},
                {"asset_path": "/Game/Characters/SK_Main", "asset_type": "SkeletalMesh"},
            ],
            "total_found": 2,
            "packages_scanned": 45,
        })
        result = server.find_material_references("/Game/Materials/M_Character")

        assert "2 references" in result
        assert "45 packages scanned" in result
        assert "/Game/Meshes/SM_Body" in result
        assert "StaticMesh" in result
        assert "/Game/Characters/SK_Main" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_no_references(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/Materials/M_Unused",
            "references": [],
            "total_found": 0,
            "packages_scanned": 30,
        })
        result = server.find_material_references("/Game/Materials/M_Unused")

        assert "0 references" in result
```

**Step 2: Run test to verify it fails**

Run: `cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py::TestFindMaterialReferences -v`
Expected: FAIL (function doesn't exist)

**Step 3: Add helper function to material_helpers.py**

Append after `layout_graph()` at end of file:

```python
# ---------------------------------------------------------------------------
# R1. find_references
# ---------------------------------------------------------------------------

def find_references(asset_path, base_path="/Game", asset_types=None):
    """Find all assets that reference the given material or material instance.

    Parameters
    ----------
    asset_path : str
        Material or MI asset path.
    base_path : str
        Narrow search scope to packages under this path.
    asset_types : str or None
        Comma-separated asset type filter (e.g. "StaticMesh,SkeletalMesh").

    Returns
    -------
    str
        JSON with references list.
    """
    try:
        mat = _load_material(asset_path)
        ar = unreal.AssetRegistryHelpers.get_asset_registry()

        # Get package name from asset path
        pkg_name, _ = _asset_parts(asset_path)
        # asset_path like /Game/Materials/M_Foo -> package_name is /Game/Materials/M_Foo
        package_name = unreal.Name(asset_path)

        referencers = ar.get_referencers(package_name)
        type_filter = None
        if asset_types:
            type_filter = set(t.strip() for t in asset_types.split(","))

        references = []
        packages_scanned = len(referencers)
        for ref_pkg in referencers:
            ref_str = str(ref_pkg)
            if not ref_str.startswith(base_path):
                continue

            # Get asset data for this package
            try:
                assets = ar.get_assets_by_package_name(ref_str)
                for asset_data in assets:
                    try:
                        asset_type = str(asset_data.asset_class_path.asset_name)
                    except Exception:
                        try:
                            asset_type = str(asset_data.asset_class)
                        except Exception:
                            asset_type = "Unknown"

                    if type_filter and asset_type not in type_filter:
                        continue

                    references.append({
                        "asset_path": str(asset_data.package_name),
                        "asset_name": str(asset_data.asset_name),
                        "asset_type": asset_type,
                    })
            except Exception:
                continue

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "references": references,
            "total_found": len(references),
            "packages_scanned": packages_scanned,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 4: Add tool to server.py**

After tool 17 (`layout_material_graph`), add:

```python
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
```

**Step 5: Run tests**

Run: `cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py::TestFindMaterialReferences -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/unreal_material_mcp/helpers/material_helpers.py src/unreal_material_mcp/server.py tests/test_server.py
git commit -m "feat: add find_material_references tool for reverse lookup"
```

---

### Task 5: New Tool — `find_breaking_changes`

**Files:**
- Modify: `src/unreal_material_mcp/helpers/material_helpers.py`
- Modify: `src/unreal_material_mcp/server.py`
- Test: `tests/test_server.py`

**Step 1: Write the failing test**

```python
class TestFindBreakingChanges:
    """Output formatting tests for find_breaking_changes."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_parameter_removal_impact(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Character",
            "target": "Roughness",
            "target_type": "parameter",
            "affected_instances": [
                {"path": "/Game/MI_Pale", "override_value": 0.3},
                {"path": "/Game/MI_Dark", "override_value": 0.8},
            ],
            "downstream_connections": [
                {"expression": "MaterialExpressionMultiply_2", "input": "A"},
            ],
        })
        result = server.find_breaking_changes(
            "/Game/M_Character", parameter_name="Roughness"
        )

        assert "Roughness" in result
        assert "/Game/MI_Pale" in result
        assert "0.3" in result
        assert "MaterialExpressionMultiply_2" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_no_breaking_changes(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Simple",
            "target": "Unused",
            "target_type": "parameter",
            "affected_instances": [],
            "downstream_connections": [],
        })
        result = server.find_breaking_changes(
            "/Game/M_Simple", parameter_name="Unused"
        )

        assert "No breaking changes" in result
```

**Step 2: Run test to verify it fails**

Run: `cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py::TestFindBreakingChanges -v`

**Step 3: Add helper function**

```python
# ---------------------------------------------------------------------------
# R2. find_breaking_changes
# ---------------------------------------------------------------------------

def find_breaking_changes(asset_path, parameter_name=None, expression_name=None,
                          base_path="/Game"):
    """Analyze what would break if a parameter or expression were removed.

    Parameters
    ----------
    asset_path : str
        Base material asset path.
    parameter_name : str or None
        Parameter to check removal of.
    expression_name : str or None
        Expression to check removal of.
    base_path : str
        Scope for MI search.

    Returns
    -------
    str
        JSON with affected instances and downstream connections.
    """
    try:
        mat = _load_material(asset_path)
        mel = _mel()

        affected_instances = []
        downstream_connections = []
        target = parameter_name or expression_name or "unknown"
        target_type = "parameter" if parameter_name else "expression"

        if parameter_name:
            # Find child instances that override this parameter
            try:
                children = mel.get_child_instances(mat)
                for child_data in children:
                    try:
                        child_path = str(child_data.package_name)
                        if not child_path.startswith(base_path):
                            continue
                        child_mat = _eal().load_asset(child_path)
                        if child_mat is None:
                            continue

                        # Check each parameter type
                        for ptype, getter_name, value_getter_name in [
                            ("Scalar", "get_scalar_parameter_names",
                             "get_material_instance_scalar_parameter_value"),
                            ("Vector", "get_vector_parameter_names",
                             "get_material_instance_vector_parameter_value"),
                            ("Texture", "get_texture_parameter_names",
                             "get_material_instance_texture_parameter_value"),
                            ("StaticSwitch", "get_static_switch_parameter_names",
                             "get_material_instance_static_switch_parameter_value"),
                        ]:
                            try:
                                names = [str(n) for n in getattr(mel, getter_name)(child_mat)]
                                if parameter_name in names:
                                    try:
                                        val = getattr(mel, value_getter_name)(
                                            child_mat, parameter_name
                                        )
                                        if ptype == "Vector":
                                            val_repr = {"r": val.r, "g": val.g,
                                                        "b": val.b, "a": val.a}
                                        elif ptype == "Texture":
                                            val_repr = val.get_path_name() if val else None
                                        else:
                                            val_repr = float(val) if ptype == "Scalar" else bool(val)
                                    except Exception:
                                        val_repr = "unknown"
                                    affected_instances.append({
                                        "path": child_path,
                                        "override_value": val_repr,
                                        "parameter_type": ptype,
                                    })
                                    break
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception:
                pass

            # Find downstream connections from the parameter expression
            try:
                full_path = _full_object_path(asset_path)
                # Find the parameter expression node
                param_classes = ["ScalarParameter", "VectorParameter",
                                 "TextureSampleParameter2D", "StaticSwitchParameter"]
                for cls in param_classes:
                    for i in range(200):
                        obj_path = f"{full_path}:MaterialExpression{cls}_{i}"
                        expr = unreal.find_object(None, obj_path)
                        if expr is None:
                            if i > 30:
                                break
                            continue
                        try:
                            pname = str(expr.get_editor_property("parameter_name"))
                        except Exception:
                            continue
                        if pname == parameter_name:
                            # Found it — note its name for downstream reference
                            downstream_connections.append({
                                "expression": _expr_id(expr),
                                "note": "This expression would be removed",
                            })
                            break
            except Exception:
                pass

        elif expression_name:
            # Trace downstream from expression
            full_path = _full_object_path(asset_path)
            if not expression_name.startswith("MaterialExpression"):
                expression_name = f"MaterialExpression{expression_name}"
            obj_path = f"{full_path}:{expression_name}"
            expr = unreal.find_object(None, obj_path)
            if expr is None:
                return _error_json(f"Expression not found: {expression_name}")

            # Check all material output pins to see if they depend on this expression
            for prop_label, prop_attr in _MATERIAL_PROPERTIES:
                try:
                    prop_enum = getattr(unreal.MaterialProperty, prop_attr)
                    node = mel.get_material_property_input_node(mat, prop_enum)
                    if node is not None:
                        # Trace backward from output pin; if our expression appears, it's downstream
                        tree_json = json.loads(trace_connections(asset_path, expression_name=None))
                        if tree_json.get("success"):
                            pin_tree = tree_json.get("output_pins", {}).get(prop_label)
                            if pin_tree:
                                def _find_in_tree(n, target_name):
                                    if n is None:
                                        return False
                                    if n.get("name") == target_name:
                                        return True
                                    for inp in n.get("inputs", []):
                                        if _find_in_tree(inp.get("connected_node"), target_name):
                                            return True
                                    return False
                                if _find_in_tree(pin_tree, expression_name):
                                    downstream_connections.append({
                                        "output_pin": prop_label,
                                        "note": f"Output pin {prop_label} depends on this expression",
                                    })
                except Exception:
                    continue

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "target": target,
            "target_type": target_type,
            "affected_instances": affected_instances,
            "downstream_connections": downstream_connections,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 4: Add tool to server.py**

```python
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
```

**Step 5: Run tests and commit**

```bash
cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py::TestFindBreakingChanges -v
git add src/unreal_material_mcp/helpers/material_helpers.py src/unreal_material_mcp/server.py tests/test_server.py
git commit -m "feat: add find_breaking_changes tool"
```

---

### Task 6: New Tool — `find_material_function_usage`

**Files:**
- Modify: `src/unreal_material_mcp/helpers/material_helpers.py`
- Modify: `src/unreal_material_mcp/server.py`
- Test: `tests/test_server.py`

**Step 1: Write the failing test**

```python
class TestFindMaterialFunctionUsage:
    """Output formatting tests for find_material_function_usage."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_usage(self, _src):
        _setup_tool_mock({
            "success": True,
            "function_path": "/Game/MF_NormalBlend",
            "materials_using": [
                {"material": "/Game/M_Character", "expression": "MFC_0"},
                {"material": "/Game/M_Weapon", "expression": "MFC_2"},
            ],
            "call_chain": None,
        })
        result = server.find_material_function_usage("/Game/MF_NormalBlend")

        assert "/Game/M_Character" in result
        assert "/Game/M_Weapon" in result
        assert "2" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_call_chain(self, _src):
        _setup_tool_mock({
            "success": True,
            "function_path": "/Game/MF_NormalBlend",
            "materials_using": [],
            "call_chain": {
                "name": "MF_NormalBlend",
                "children": [
                    {"name": "MF_PackNormal", "children": []},
                    {"name": "MF_UnpackNormal", "children": [
                        {"name": "MF_TextureUtility", "children": []},
                    ]},
                ],
            },
        })
        result = server.find_material_function_usage(
            "/Game/MF_NormalBlend", include_chain=True
        )

        assert "MF_NormalBlend" in result
        assert "MF_PackNormal" in result
        assert "MF_TextureUtility" in result
```

**Step 2-6:** Follow the same pattern — add helper, add tool, run tests, commit.

**Helper function (`material_helpers.py`):**

```python
# ---------------------------------------------------------------------------
# R3. find_function_usage
# ---------------------------------------------------------------------------

def find_function_usage(function_path, base_path="/Game", include_chain=False):
    """Find materials using a material function, optionally trace call chain.

    Parameters
    ----------
    function_path : str
        MaterialFunction asset path.
    base_path : str
        Scope for material search.
    include_chain : bool
        If True, include nested function dependency tree.

    Returns
    -------
    str
        JSON with usage list and optional call chain.
    """
    try:
        ar = unreal.AssetRegistryHelpers.get_asset_registry()
        mel = _mel()

        # Find all materials under base_path
        all_assets = ar.get_assets_by_path(base_path, recursive=True)
        materials_using = []

        for asset_data in all_assets:
            try:
                class_name = str(asset_data.asset_class_path.asset_name)
            except Exception:
                continue
            if class_name != "Material":
                continue

            mat_path = str(asset_data.package_name)
            # Check if this material has MaterialFunctionCall expressions referencing our function
            try:
                fn_data = json.loads(
                    scan_all_expressions(mat_path, class_filter="MaterialFunctionCall")
                )
                if fn_data.get("success"):
                    for expr in fn_data.get("expressions", []):
                        fn_ref = expr.get("function", "")
                        if fn_ref and function_path in fn_ref:
                            materials_using.append({
                                "material": mat_path,
                                "expression": expr.get("name", "?"),
                            })
            except Exception:
                continue

        # Call chain
        call_chain = None
        if include_chain:
            call_chain = _trace_function_chain(function_path, visited=set())

        return json.dumps({
            "success": True,
            "function_path": function_path,
            "materials_using": materials_using,
            "call_chain": call_chain,
        })
    except Exception as exc:
        return _error_json(exc)


def _trace_function_chain(function_path, visited=None, depth=0, max_depth=10):
    """Recursively trace nested MaterialFunctionCall dependencies."""
    if visited is None:
        visited = set()
    if function_path in visited or depth > max_depth:
        return {"name": function_path.rsplit("/", 1)[-1], "children": [], "cycle": True}
    visited.add(function_path)

    _, fn_name = _asset_parts(function_path)
    node = {"name": fn_name, "path": function_path, "children": []}

    try:
        fn_data = json.loads(
            scan_all_expressions(function_path, class_filter="MaterialFunctionCall")
        )
        if fn_data.get("success"):
            for expr in fn_data.get("expressions", []):
                child_path = expr.get("function")
                if child_path:
                    child = _trace_function_chain(child_path, visited, depth + 1, max_depth)
                    node["children"].append(child)
    except Exception:
        pass

    return node
```

**Tool in server.py:**

```python
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
```

**Commit:**
```bash
git commit -m "feat: add find_material_function_usage tool"
```

---

### Task 7: New Tool — `search_material_instances`

**Step 1: Write the failing test**

```python
class TestSearchMaterialInstances:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_dead_instances(self, _src):
        _setup_tool_mock({
            "success": True,
            "base_path": "/Game",
            "filter_type": "dead",
            "results": [
                {"path": "/Game/MI_Old", "parent": "/Game/M_Base", "override_count": 0},
            ],
            "total_scanned": 20,
        })
        result = server.search_material_instances(filter_type="dead")

        assert "dead" in result.lower() or "Dead" in result
        assert "/Game/MI_Old" in result
        assert "0 overrides" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_by_parent(self, _src):
        _setup_tool_mock({
            "success": True,
            "base_path": "/Game",
            "filter_type": "by_parent",
            "results": [
                {"path": "/Game/MI_A", "parent": "/Game/M_Base", "override_count": 3},
                {"path": "/Game/MI_B", "parent": "/Game/M_Base", "override_count": 1},
            ],
            "total_scanned": 20,
        })
        result = server.search_material_instances(
            parent_path="/Game/M_Base", filter_type="by_parent"
        )

        assert "/Game/MI_A" in result
        assert "/Game/MI_B" in result
```

**Helper function:**

```python
# ---------------------------------------------------------------------------
# R4. search_material_instances
# ---------------------------------------------------------------------------

def search_instances(base_path="/Game", parent_path=None, filter_type="all"):
    """Search for material instances with various filters.

    Parameters
    ----------
    base_path : str
        Content path to search under.
    parent_path : str or None
        Filter by parent material/MI path (for "by_parent" filter).
    filter_type : str
        One of: "all", "by_parent", "dead" (0 overrides), "orphaned" (missing parent).

    Returns
    -------
    str
        JSON with results list.
    """
    try:
        ar = unreal.AssetRegistryHelpers.get_asset_registry()
        mel = _mel()
        all_assets = ar.get_assets_by_path(base_path, recursive=True)

        results = []
        total_scanned = 0

        for asset_data in all_assets:
            try:
                class_name = str(asset_data.asset_class_path.asset_name)
            except Exception:
                continue
            if class_name != "MaterialInstanceConstant":
                continue

            total_scanned += 1
            mi_path = str(asset_data.package_name)

            try:
                mi = _eal().load_asset(mi_path)
                if mi is None:
                    continue
            except Exception:
                continue

            # Get parent
            try:
                parent = mi.get_editor_property("parent")
                parent_path_str = parent.get_path_name() if parent else None
            except Exception:
                parent_path_str = None

            # Count overrides (approximate: count parameter names across types)
            override_count = 0
            for getter in (mel.get_scalar_parameter_names,
                           mel.get_vector_parameter_names,
                           mel.get_texture_parameter_names,
                           mel.get_static_switch_parameter_names):
                try:
                    override_count += len(list(getter(mi)))
                except Exception:
                    pass

            entry = {
                "path": mi_path,
                "name": str(asset_data.asset_name),
                "parent": parent_path_str,
                "override_count": override_count,
            }

            if filter_type == "all":
                results.append(entry)
            elif filter_type == "by_parent":
                if parent_path and parent_path_str and parent_path in parent_path_str:
                    results.append(entry)
            elif filter_type == "dead":
                if override_count == 0:
                    results.append(entry)
            elif filter_type == "orphaned":
                if parent_path_str is None:
                    results.append(entry)
            else:
                results.append(entry)

        return json.dumps({
            "success": True,
            "base_path": base_path,
            "filter_type": filter_type,
            "results": results,
            "total_scanned": total_scanned,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Tool in server.py:**

```python
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
```

**Commit:**
```bash
git commit -m "feat: add search_material_instances tool"
```

---

### Task 8: New Tool — `set_expression_property`

**Step 1: Write the failing test**

```python
class TestSetExpressionProperty:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_property_set(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "expression_name": "MaterialExpressionScalarParameter_0",
            "property_name": "parameter_name",
            "old_value": "Param",
            "new_value": "Roughness",
        })
        result = server.set_expression_property(
            "/Game/M_Foo", "MaterialExpressionScalarParameter_0",
            "parameter_name", "Roughness"
        )

        assert "parameter_name" in result
        assert "Roughness" in result
        assert "Param" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_expression_not_found(self, _src):
        _setup_tool_mock({
            "success": False,
            "error": "Expression not found: Missing_0",
        })
        result = server.set_expression_property(
            "/Game/M_Foo", "Missing_0", "parameter_name", "Test"
        )

        assert "Error:" in result
```

**Helper function:**

```python
# ---------------------------------------------------------------------------
# W8. set_expression_property
# ---------------------------------------------------------------------------

def set_expression_property(asset_path, expression_name, property_name, value):
    """Set a property on an existing material expression.

    Parameters
    ----------
    asset_path : str
        Base material asset path.
    expression_name : str
        Expression object name.
    property_name : str
        Property to set (e.g. "parameter_name", "texture", "code").
    value
        New value. Type depends on property.

    Returns
    -------
    str
        JSON with old and new values.
    """
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot edit expressions on a MaterialInstanceConstant.")

        full_path = _full_object_path(asset_path)
        if not expression_name.startswith("MaterialExpression"):
            expression_name = f"MaterialExpression{expression_name}"

        obj_path = f"{full_path}:{expression_name}"
        expr = unreal.find_object(None, obj_path)
        if expr is None:
            return _error_json(f"Expression not found: {expression_name}")

        # Read old value
        try:
            old_val = expr.get_editor_property(property_name)
            if hasattr(old_val, 'get_path_name'):
                old_repr = old_val.get_path_name()
            elif hasattr(old_val, 'r'):
                old_repr = {"r": old_val.r, "g": old_val.g, "b": old_val.b, "a": old_val.a}
            else:
                old_repr = str(old_val)
        except Exception:
            old_repr = None

        # Handle special property types
        if property_name == "texture":
            # value is an asset path string
            tex = _eal().load_asset(str(value))
            if tex is None:
                return _error_json(f"Texture not found: {value}")
            expr.set_editor_property(property_name, tex)
            new_repr = str(value)
        elif property_name in ("r", "g", "b", "a") and isinstance(value, bool):
            expr.set_editor_property(property_name, bool(value))
            new_repr = str(value)
        elif property_name == "constant" and isinstance(value, dict):
            lc = unreal.LinearColor(
                r=float(value.get("r", 0)),
                g=float(value.get("g", 0)),
                b=float(value.get("b", 0)),
                a=float(value.get("a", 1)),
            )
            expr.set_editor_property(property_name, lc)
            new_repr = value
        else:
            # Try setting directly; Python/UE will handle type coercion
            expr.set_editor_property(property_name, value)
            new_repr = str(value)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "expression_name": expression_name,
            "property_name": property_name,
            "old_value": old_repr,
            "new_value": new_repr,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Tool in server.py:**

```python
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
```

**Commit:**
```bash
git commit -m "feat: add set_expression_property tool"
```

---

### Task 9: New Tool — `duplicate_expression_subgraph`

**Step 1: Write failing test**

```python
class TestDuplicateExpressionSubgraph:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_duplication(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "root_expression": "MaterialExpressionMultiply_0",
            "duplicated": {
                "MaterialExpressionMultiply_0": "MaterialExpressionMultiply_5",
                "MaterialExpressionScalarParameter_0": "MaterialExpressionScalarParameter_3",
            },
            "count": 2,
        })
        result = server.duplicate_expression_subgraph(
            "/Game/M_Foo", "MaterialExpressionMultiply_0"
        )

        assert "2" in result
        assert "MaterialExpressionMultiply_5" in result
```

**Helper function:**

```python
# ---------------------------------------------------------------------------
# W9. duplicate_subgraph
# ---------------------------------------------------------------------------

def duplicate_subgraph(asset_path, root_expression, offset_x=0, offset_y=300):
    """Duplicate an expression and all its upstream inputs within the same material.

    Parameters
    ----------
    asset_path : str
        Base material path.
    root_expression : str
        Expression to duplicate (root of subgraph).
    offset_x, offset_y : int
        Position offset for duplicated nodes.

    Returns
    -------
    str
        JSON with mapping of original→duplicate names.
    """
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot duplicate on a MaterialInstanceConstant.")

        mel = _mel()
        full_path = _full_object_path(asset_path)

        if not root_expression.startswith("MaterialExpression"):
            root_expression = f"MaterialExpression{root_expression}"

        root_obj = unreal.find_object(None, f"{full_path}:{root_expression}")
        if root_obj is None:
            return _error_json(f"Expression not found: {root_expression}")

        # Collect subgraph via BFS
        to_visit = [root_obj]
        visited = set()
        expressions_to_dup = []

        while to_visit:
            expr = to_visit.pop(0)
            eid = _expr_id(expr)
            if eid in visited:
                continue
            visited.add(eid)
            expressions_to_dup.append(expr)

            # Get inputs
            try:
                inputs = mel.get_inputs_for_material_expression(mat, expr)
                for inp in inputs:
                    if inp is not None:
                        to_visit.append(inp)
            except Exception:
                pass

        # Duplicate each expression
        name_map = {}  # original_name -> (original_expr, new_expr)
        for expr in expressions_to_dup:
            dup = mel.duplicate_material_expression(mat, None, expr)
            if dup is not None:
                # Offset position
                try:
                    pos = _expr_position(expr)
                    dup.set_editor_property(
                        "material_expression_editor_x", pos["x"] + offset_x
                    )
                    dup.set_editor_property(
                        "material_expression_editor_y", pos["y"] + offset_y
                    )
                except Exception:
                    pass
                name_map[_expr_id(expr)] = (_expr_id(dup))

        # Reconnect duplicated nodes
        for expr in expressions_to_dup:
            orig_name = _expr_id(expr)
            dup_name = name_map.get(orig_name)
            if not dup_name:
                continue

            dup_expr = unreal.find_object(None, f"{full_path}:{dup_name}")
            if dup_expr is None:
                continue

            try:
                inputs = mel.get_inputs_for_material_expression(mat, expr)
                input_names = mel.get_material_expression_input_names(expr)
                for idx, inp_expr in enumerate(inputs):
                    if inp_expr is None:
                        continue
                    inp_name = _expr_id(inp_expr)
                    dup_inp_name = name_map.get(inp_name)
                    if dup_inp_name:
                        dup_inp = unreal.find_object(None, f"{full_path}:{dup_inp_name}")
                        if dup_inp:
                            in_pin = str(input_names[idx]) if idx < len(input_names) else ""
                            # Get output name
                            out_name = ""
                            try:
                                mel.get_input_node_output_name_for_material_expression(
                                    expr, inp_expr
                                )
                            except Exception:
                                pass
                            mel.connect_material_expressions(dup_inp, out_name, dup_expr, in_pin)
            except Exception:
                pass

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "root_expression": root_expression,
            "duplicated": name_map,
            "count": len(name_map),
        })
    except Exception as exc:
        return _error_json(exc)
```

**Tool in server.py:**

```python
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
```

**Commit:**
```bash
git commit -m "feat: add duplicate_expression_subgraph tool"
```

---

### Task 10: New Tool — `manage_material_parameter`

**Step 1: Write failing test**

```python
class TestManageMaterialParameter:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_add_parameter(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "action": "add",
            "parameter_name": "Roughness",
            "parameter_type": "scalar",
            "expression_name": "MaterialExpressionScalarParameter_5",
        })
        result = server.manage_material_parameter(
            "/Game/M_Foo", "add", "Roughness", parameter_type="scalar"
        )

        assert "Added" in result
        assert "Roughness" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_rename_parameter(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "action": "rename",
            "old_name": "Param1",
            "new_name": "Roughness",
        })
        result = server.manage_material_parameter(
            "/Game/M_Foo", "rename", "Param1", new_name="Roughness"
        )

        assert "Renamed" in result or "renamed" in result
        assert "Roughness" in result
```

**Helper function:**

```python
# ---------------------------------------------------------------------------
# W10. manage_parameter
# ---------------------------------------------------------------------------

def manage_parameter(asset_path, action, parameter_name, new_name=None,
                     parameter_type=None, default_value=None, group=None):
    """Add, remove, or rename a material parameter.

    Parameters
    ----------
    asset_path : str
        Base material path.
    action : str
        "add", "remove", or "rename".
    parameter_name : str
        Target parameter name.
    new_name : str or None
        New name for "rename" action.
    parameter_type : str or None
        For "add": "scalar", "vector", "texture", "static_switch".
    default_value
        For "add": default value.
    group : str or None
        For "add": parameter group name.

    Returns
    -------
    str
        JSON confirmation.
    """
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot manage parameters on a MaterialInstanceConstant.")

        mel = _mel()
        full_path = _full_object_path(asset_path)

        if action == "add":
            if not parameter_type:
                return _error_json("parameter_type required for 'add' action")

            type_to_class = {
                "scalar": "ScalarParameter",
                "vector": "VectorParameter",
                "texture": "TextureSampleParameter2D",
                "static_switch": "StaticSwitchParameter",
            }
            expr_class_name = type_to_class.get(parameter_type.lower())
            if not expr_class_name:
                return _error_json(f"Unknown parameter_type: {parameter_type}")

            full_class = f"MaterialExpression{expr_class_name}"
            expr_class = getattr(unreal, full_class, None)
            if expr_class is None:
                return _error_json(f"Class not found: {full_class}")

            expr = mel.create_material_expression(mat, expr_class, 0, 0)
            expr.set_editor_property("parameter_name", parameter_name)

            if group:
                try:
                    expr.set_editor_property("group", group)
                except Exception:
                    pass

            if default_value is not None:
                try:
                    if parameter_type.lower() == "scalar":
                        expr.set_editor_property("default_value", float(default_value))
                    elif parameter_type.lower() == "vector":
                        if isinstance(default_value, dict):
                            lc = unreal.LinearColor(
                                r=float(default_value.get("r", 0)),
                                g=float(default_value.get("g", 0)),
                                b=float(default_value.get("b", 0)),
                                a=float(default_value.get("a", 1)),
                            )
                            expr.set_editor_property("default_value", lc)
                    elif parameter_type.lower() == "static_switch":
                        expr.set_editor_property(
                            "default_value",
                            bool(default_value) if isinstance(default_value, bool)
                            else str(default_value).lower() in ("true", "1", "yes")
                        )
                except Exception:
                    pass

            return json.dumps({
                "success": True,
                "asset_path": asset_path,
                "action": "add",
                "parameter_name": parameter_name,
                "parameter_type": parameter_type,
                "expression_name": _expr_id(expr),
            })

        elif action == "remove":
            # Find parameter expression by name
            param_classes = ["ScalarParameter", "VectorParameter",
                             "TextureSampleParameter2D", "StaticSwitchParameter",
                             "TextureObjectParameter"]
            found_expr = None
            for cls in param_classes:
                for i in range(200):
                    obj_path = f"{full_path}:MaterialExpression{cls}_{i}"
                    expr = unreal.find_object(None, obj_path)
                    if expr is None:
                        if i > 30:
                            break
                        continue
                    try:
                        pname = str(expr.get_editor_property("parameter_name"))
                        if pname == parameter_name:
                            found_expr = expr
                            break
                    except Exception:
                        continue
                if found_expr:
                    break

            if found_expr is None:
                return _error_json(f"Parameter '{parameter_name}' not found")

            expr_name = _expr_id(found_expr)
            mel.delete_material_expression(mat, found_expr)

            return json.dumps({
                "success": True,
                "asset_path": asset_path,
                "action": "remove",
                "parameter_name": parameter_name,
                "expression_name": expr_name,
            })

        elif action == "rename":
            if not new_name:
                return _error_json("new_name required for 'rename' action")

            param_classes = ["ScalarParameter", "VectorParameter",
                             "TextureSampleParameter2D", "StaticSwitchParameter",
                             "TextureObjectParameter"]
            found_expr = None
            for cls in param_classes:
                for i in range(200):
                    obj_path = f"{full_path}:MaterialExpression{cls}_{i}"
                    expr = unreal.find_object(None, obj_path)
                    if expr is None:
                        if i > 30:
                            break
                        continue
                    try:
                        pname = str(expr.get_editor_property("parameter_name"))
                        if pname == parameter_name:
                            found_expr = expr
                            break
                    except Exception:
                        continue
                if found_expr:
                    break

            if found_expr is None:
                return _error_json(f"Parameter '{parameter_name}' not found")

            found_expr.set_editor_property("parameter_name", new_name)

            return json.dumps({
                "success": True,
                "asset_path": asset_path,
                "action": "rename",
                "old_name": parameter_name,
                "new_name": new_name,
            })

        else:
            return _error_json(f"Unknown action: {action}")

    except Exception as exc:
        return _error_json(exc)
```

**Tool in server.py:**

```python
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
```

**Commit:**
```bash
git commit -m "feat: add manage_material_parameter tool (add/remove/rename)"
```

---

### Task 11: New Tool — `rename_parameter_cascade`

**Step 1: Write failing test**

```python
class TestRenameParameterCascade:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_cascade_rename(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Base",
            "old_name": "Param1",
            "new_name": "Roughness",
            "material_renamed": True,
            "instances_updated": 3,
            "instances_scanned": 10,
        })
        result = server.rename_parameter_cascade(
            "/Game/M_Base", "Param1", "Roughness"
        )

        assert "Param1" in result
        assert "Roughness" in result
        assert "3" in result
```

**Helper + tool follow the same pattern.** The helper calls `manage_parameter(rename)` on the base material, then iterates child instances to update overrides. The tool formats results.

**Helper:**

```python
# ---------------------------------------------------------------------------
# W11. rename_parameter_cascade
# ---------------------------------------------------------------------------

def rename_parameter_cascade(asset_path, old_name, new_name, base_path="/Game"):
    """Rename a parameter across a material and all its child instances.

    Parameters
    ----------
    asset_path : str
        Base material path.
    old_name : str
        Current parameter name.
    new_name : str
        New parameter name.
    base_path : str
        Scope for child instance search.

    Returns
    -------
    str
        JSON with rename results.
    """
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot cascade rename from a MaterialInstanceConstant.")

        mel = _mel()

        # Rename on base material
        rename_result = json.loads(
            manage_parameter(asset_path, "rename", old_name, new_name=new_name)
        )
        if not rename_result.get("success"):
            return json.dumps(rename_result)

        # Find and update child instances
        instances_updated = 0
        instances_scanned = 0

        try:
            children = mel.get_child_instances(mat)
            for child_data in children:
                instances_scanned += 1
                try:
                    child_path = str(child_data.package_name)
                    if not child_path.startswith(base_path):
                        continue
                    child = _eal().load_asset(child_path)
                    if child is None or not _is_material_instance(child):
                        continue

                    # Check if child overrides the old parameter name
                    # Note: after renaming the base material parameter, the child's
                    # override key may still reference the old name internally.
                    # We need to update the MI.
                    mel.update_material_instance(child)
                    instances_updated += 1
                except Exception:
                    continue
        except Exception:
            pass

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "old_name": old_name,
            "new_name": new_name,
            "material_renamed": True,
            "instances_updated": instances_updated,
            "instances_scanned": instances_scanned,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Tool:**

```python
# ---------------------------------------------------------------------------
# Tool 25: rename_parameter_cascade
# ---------------------------------------------------------------------------

@mcp.tool()
def rename_parameter_cascade(
    asset_path: str,
    old_name: str,
    new_name: str,
    base_path: str = "/Game",
) -> str:
    """Rename a parameter across a material and all its child instances.

    Args:
        asset_path: Base material path
        old_name: Current parameter name
        new_name: New parameter name
        base_path: Scope for child instance search
    """
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
```

**Commit:**
```bash
git commit -m "feat: add rename_parameter_cascade tool"
```

---

### Task 12: New Tools — `create_material_instance` + `reparent_material_instance`

**Step 1: Write failing tests**

```python
class TestCreateMaterialInstance:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_created(self, _src):
        _setup_tool_mock({
            "success": True,
            "instance_path": "/Game/Materials/MI_Red",
            "parent_path": "/Game/Materials/M_Base",
        })
        result = server.create_material_instance(
            "/Game/Materials/M_Base", "MI_Red"
        )

        assert "Created" in result
        assert "MI_Red" in result
        assert "/Game/Materials/M_Base" in result


class TestReparentMaterialInstance:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_reparented(self, _src):
        _setup_tool_mock({
            "success": True,
            "instance_path": "/Game/MI_Foo",
            "old_parent": "/Game/M_Old",
            "new_parent": "/Game/M_New",
        })
        result = server.reparent_material_instance(
            "/Game/MI_Foo", "/Game/M_New"
        )

        assert "Reparented" in result or "reparent" in result.lower()
        assert "/Game/M_New" in result
```

**Helper functions:**

```python
# ---------------------------------------------------------------------------
# W12. create_instance
# ---------------------------------------------------------------------------

def create_instance(parent_path, instance_name, destination_path=""):
    """Create a new MaterialInstanceConstant from a parent material.

    Parameters
    ----------
    parent_path : str
        Parent material or MI path.
    instance_name : str
        Name for the new MI.
    destination_path : str
        Content path for the new MI. Defaults to same dir as parent.

    Returns
    -------
    str
        JSON with new instance path.
    """
    try:
        parent = _load_material(parent_path)

        if not destination_path:
            pkg, _ = _asset_parts(parent_path)
            destination_path = pkg

        at = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.MaterialInstanceConstantFactoryNew()

        new_asset = at.create_asset(
            instance_name, destination_path,
            unreal.MaterialInstanceConstant, factory
        )
        if new_asset is None:
            return _error_json(f"Failed to create MI: {instance_name}")

        _mel().set_material_instance_parent(new_asset, parent)

        instance_path = f"{destination_path}/{instance_name}"

        return json.dumps({
            "success": True,
            "instance_path": instance_path,
            "parent_path": parent_path,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# W13. reparent_instance
# ---------------------------------------------------------------------------

def reparent_instance(instance_path, new_parent_path):
    """Reparent a MaterialInstanceConstant to a different parent.

    Parameters
    ----------
    instance_path : str
        MI to reparent.
    new_parent_path : str
        New parent material or MI.

    Returns
    -------
    str
        JSON with old and new parent.
    """
    try:
        mi = _load_material(instance_path)
        if not _is_material_instance(mi):
            return _error_json(f"Not a MaterialInstanceConstant: {instance_path}")

        new_parent = _load_material(new_parent_path)
        mel = _mel()

        # Get old parent
        try:
            old_parent = mi.get_editor_property("parent")
            old_parent_path = old_parent.get_path_name() if old_parent else None
        except Exception:
            old_parent_path = None

        mel.set_material_instance_parent(mi, new_parent)
        mel.update_material_instance(mi)

        return json.dumps({
            "success": True,
            "instance_path": instance_path,
            "old_parent": old_parent_path,
            "new_parent": new_parent_path,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Tools in server.py:**

```python
# ---------------------------------------------------------------------------
# Tool 26: create_material_instance
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool 27: reparent_material_instance
# ---------------------------------------------------------------------------

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
```

**Commit:**
```bash
git commit -m "feat: add create_material_instance and reparent_material_instance tools"
```

---

### Task 13: New Tool — `batch_update_materials`

**Step 1: Write failing test**

```python
class TestBatchUpdateMaterials:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_swap_texture(self, _src):
        _setup_tool_mock({
            "success": True,
            "operation": "swap_texture",
            "processed": 5,
            "modified": 3,
            "modified_assets": ["/Game/M_A", "/Game/M_B", "/Game/M_C"],
            "errors": [],
        })
        result = server.batch_update_materials(
            "/Game", "swap_texture",
            operation_args='{"old_texture": "/Game/T_Old", "new_texture": "/Game/T_New"}'
        )

        assert "3 modified" in result or "modified: 3" in result.lower()
        assert "/Game/M_A" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_no_matches(self, _src):
        _setup_tool_mock({
            "success": True,
            "operation": "set_parameter",
            "processed": 10,
            "modified": 0,
            "modified_assets": [],
            "errors": [],
        })
        result = server.batch_update_materials(
            "/Game", "set_parameter",
            operation_args='{"parameter_name": "Test", "value": "1.0"}'
        )

        assert "0" in result
```

**Helper function:**

```python
# ---------------------------------------------------------------------------
# W14. batch_update
# ---------------------------------------------------------------------------

def batch_update(base_path, operation, filter_query="", filter_type="name",
                 operation_args=None):
    """Batch update materials: swap textures, set parameters, or set attributes.

    Parameters
    ----------
    base_path : str
        Content path to search under.
    operation : str
        "swap_texture", "set_parameter", or "set_attribute".
    filter_query : str
        Filter materials by name/parameter/etc.
    filter_type : str
        "name", "parameter", "expression", "shading_model".
    operation_args : dict or None
        Operation-specific arguments.

    Returns
    -------
    str
        JSON with results.
    """
    try:
        if operation_args is None:
            operation_args = {}

        # Find target materials
        search_result = json.loads(
            search_materials_in_path(base_path, query=filter_query, filter_type=filter_type)
        )
        if not search_result.get("success"):
            return json.dumps(search_result)

        targets = search_result.get("results", [])
        mel = _mel()
        modified_assets = []
        errors = []

        for target in targets:
            target_path = target.get("asset_path")
            target_class = target.get("class", "Material")
            try:
                mat = _eal().load_asset(target_path)
                if mat is None:
                    continue

                if operation == "swap_texture":
                    old_tex = operation_args.get("old_texture", "")
                    new_tex_path = operation_args.get("new_texture", "")
                    if not old_tex or not new_tex_path:
                        continue

                    # Only works on base materials (expressions)
                    if target_class != "Material":
                        continue

                    full_path = _full_object_path(target_path)
                    swapped = False
                    tex_classes = ["TextureSample", "TextureSampleParameter2D",
                                   "TextureObjectParameter"]
                    for cls in tex_classes:
                        for i in range(200):
                            obj_path = f"{full_path}:MaterialExpression{cls}_{i}"
                            expr = unreal.find_object(None, obj_path)
                            if expr is None:
                                if i > 30:
                                    break
                                continue
                            try:
                                tex = expr.get_editor_property("texture")
                                if tex and old_tex in tex.get_path_name():
                                    new_tex = _eal().load_asset(new_tex_path)
                                    if new_tex:
                                        expr.set_editor_property("texture", new_tex)
                                        swapped = True
                            except Exception:
                                continue

                    if swapped:
                        modified_assets.append(target_path)

                elif operation == "set_parameter":
                    param_name = operation_args.get("parameter_name", "")
                    param_value = operation_args.get("value")
                    param_type = operation_args.get("parameter_type")
                    if not param_name:
                        continue

                    if target_class != "MaterialInstanceConstant":
                        continue

                    try:
                        result = json.loads(
                            set_instance_parameter(target_path, param_name, param_value, param_type)
                        )
                        if result.get("success"):
                            modified_assets.append(target_path)
                    except Exception as e:
                        errors.append({"path": target_path, "error": str(e)})

                elif operation == "set_attribute":
                    prop_name = operation_args.get("property_name", "")
                    prop_value = operation_args.get("value", "")
                    if not prop_name:
                        continue

                    if target_class != "Material":
                        continue

                    try:
                        result = json.loads(
                            set_property(target_path, prop_name, prop_value)
                        )
                        if result.get("success"):
                            modified_assets.append(target_path)
                    except Exception as e:
                        errors.append({"path": target_path, "error": str(e)})

            except Exception as e:
                errors.append({"path": target_path, "error": str(e)})

        return json.dumps({
            "success": True,
            "operation": operation,
            "processed": len(targets),
            "modified": len(modified_assets),
            "modified_assets": modified_assets,
            "errors": errors,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Tool:**

```python
# ---------------------------------------------------------------------------
# Tool 28: batch_update_materials
# ---------------------------------------------------------------------------

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
```

**Commit:**
```bash
git commit -m "feat: add batch_update_materials tool"
```

---

### Task 14: Update CLAUDE.md and Run Full Test Suite

**Step 1: Run all tests**

```bash
cd /c/Projects/unreal-material-mcp && python -m pytest tests/test_server.py -v
```
Expected: All PASS

**Step 2: Update CLAUDE.md tool count and descriptions**

Update the tools list in CLAUDE.md to reflect the new 28-tool inventory.

**Step 3: Final commit**

```bash
git add -A
git commit -m "docs: update CLAUDE.md with all 28 tools"
```

---

## Summary

| Task | What | New/Extend | Tools |
|------|------|-----------|-------|
| 1 | Static switch values | Extend | `get_material_parameters` |
| 2 | Texture sizes/formats | Extend | `get_material_dependencies` |
| 3 | Compile status/errors | Extend | `get_material_stats` |
| 4 | Reverse lookup | New #18 | `find_material_references` |
| 5 | Breaking changes | New #19 | `find_breaking_changes` |
| 6 | MF usage map | New #20 | `find_material_function_usage` |
| 7 | MI search/filter | New #21 | `search_material_instances` |
| 8 | Edit expression props | New #22 | `set_expression_property` |
| 9 | Duplicate subgraph | New #23 | `duplicate_expression_subgraph` |
| 10 | Param management | New #24 | `manage_material_parameter` |
| 11 | Cascade rename | New #25 | `rename_parameter_cascade` |
| 12 | MI create + reparent | New #26-27 | `create_material_instance`, `reparent_material_instance` |
| 13 | Bulk operations | New #28 | `batch_update_materials` |
| 14 | Final cleanup | Docs | CLAUDE.md update |
