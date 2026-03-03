# Material MCP Tier 2 Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 12 new tools (diagnostics, dependencies, function inspection, instance chain, compare, instance editing, graph editing) to the material MCP server, bringing the total from 5 to 17.

**Architecture:** Same two-layer pattern as Tier 1 — helper functions in `material_helpers.py` (runs inside UE editor) and MCP tool definitions in `server.py` (runs on host). Each new tool = one helper function + one server tool + tests.

**Tech Stack:** Python 3.12+, FastMCP, UE 5.7 Python API (MaterialEditingLibrary, EditorAssetLibrary, AssetRegistry)

---

### Task 1: Group A Helper Functions (5 read-only)

Add 5 new functions to `helpers/material_helpers.py` for the read-only extension tools. All return JSON strings following the existing `{"success": True, ...}` envelope pattern.

**Files:**
- Modify: `src/unreal_material_mcp/helpers/material_helpers.py`

**Step 1: Add `get_stats(asset_path)` function**

Append after `search_materials_in_path`. Uses `_mel().get_statistics()` to get `FMaterialStatistics`, then runs disconnected/unused analysis by comparing scanned expressions against traced connections.

```python
# ---------------------------------------------------------------------------
# 6. get_stats
# ---------------------------------------------------------------------------

def get_stats(asset_path):
    """Return JSON with shader statistics and basic diagnostic warnings."""
    try:
        mat = _load_material(asset_path)

        if _is_material_instance(mat):
            return _error_json("get_stats requires a base Material, not a MaterialInstanceConstant")

        mel = _mel()
        stats_obj = mel.get_statistics(mat)

        stats = {
            "vertex_shader_instructions": int(stats_obj.num_vertex_shader_instructions),
            "pixel_shader_instructions": int(stats_obj.num_pixel_shader_instructions),
            "num_samplers": int(stats_obj.num_samplers),
            "vertex_texture_samples": int(stats_obj.num_vertex_texture_samples),
            "pixel_texture_samples": int(stats_obj.num_pixel_texture_samples),
            "virtual_texture_samples": int(stats_obj.num_virtual_texture_samples),
            "uv_scalars": int(stats_obj.num_uv_scalars),
            "interpolator_scalars": int(stats_obj.num_interpolator_scalars),
        }

        # Basic warnings
        warnings = []
        if stats["num_samplers"] > 16:
            warnings.append(f"High sampler count: {stats['num_samplers']} (platform limit is typically 16)")
        if stats["pixel_shader_instructions"] > 500:
            warnings.append(f"High pixel shader instructions: {stats['pixel_shader_instructions']} (may cause performance issues)")

        # Disconnected expression analysis
        # Scan all expressions, then trace from output pins to find connected ones
        scan_result = json.loads(scan_all_expressions(asset_path))
        all_expr_names = set()
        param_expr_names = set()
        if scan_result.get("success"):
            for expr in scan_result.get("expressions", []):
                name = expr.get("name", "")
                all_expr_names.add(name)
                if "Parameter" in expr.get("class", ""):
                    param_expr_names.add(name)

        # Trace from output pins to find connected expressions
        trace_result = json.loads(trace_connections(asset_path))
        connected_names = set()
        if trace_result.get("success"):
            def _collect_names(node):
                if node is None or not isinstance(node, dict):
                    return
                name = node.get("name", "")
                if name:
                    connected_names.add(name)
                for inp in node.get("inputs", []):
                    _collect_names(inp.get("connected_node"))

            for pin_name, tree in trace_result.get("output_pins", {}).items():
                _collect_names(tree)

        # Expressions not in any output pin trace = disconnected
        # Exclude Comments — they're never connected
        disconnected = []
        for name in all_expr_names:
            if name not in connected_names and "Comment" not in name:
                disconnected.append(name)

        if disconnected:
            warnings.append(f"Disconnected expressions ({len(disconnected)}): {', '.join(sorted(disconnected)[:10])}")
            if len(disconnected) > 10:
                warnings[-1] += f" ... and {len(disconnected) - 10} more"

        # Unused parameters = parameter expressions not in connected set
        unused_params = [n for n in param_expr_names if n not in connected_names]
        if unused_params:
            warnings.append(f"Unused parameters ({len(unused_params)}): {', '.join(sorted(unused_params)[:10])}")

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "stats": stats,
            "warnings": warnings,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 2: Add `get_dependencies(asset_path)` function**

```python
# ---------------------------------------------------------------------------
# 7. get_dependencies
# ---------------------------------------------------------------------------

def get_dependencies(asset_path):
    """Return JSON listing textures, material functions, and parameter sources."""
    try:
        mat = _load_material(asset_path)
        mel = _mel()

        result = {
            "success": True,
            "asset_path": asset_path,
            "textures": [],
            "material_functions": [],
            "parameter_sources": [],
        }

        # Textures used
        if not _is_material_instance(mat):
            try:
                textures = mel.get_used_textures(mat)
                for tex in textures:
                    if tex is not None:
                        result["textures"].append(tex.get_path_name())
            except Exception:
                pass

        # Material functions — scan MaterialFunctionCall expressions
        if not _is_material_instance(mat):
            scan = json.loads(scan_all_expressions(asset_path, class_filter="MaterialFunctionCall"))
            if scan.get("success"):
                for expr in scan.get("expressions", []):
                    fn_path = expr.get("function")
                    if fn_path:
                        result["material_functions"].append({
                            "expression": expr.get("name", ""),
                            "function_path": fn_path,
                        })

        # Parameter sources
        try:
            source_getters = [
                ("Scalar", mel.get_scalar_parameter_source),
                ("Vector", mel.get_vector_parameter_source),
                ("Texture", mel.get_texture_parameter_source),
                ("StaticSwitch", mel.get_static_switch_parameter_source),
            ]
            name_getters = [
                mel.get_scalar_parameter_names,
                mel.get_vector_parameter_names,
                mel.get_texture_parameter_names,
                mel.get_static_switch_parameter_names,
            ]
            for (ptype, source_getter), name_getter in zip(source_getters, name_getters):
                try:
                    names = name_getter(mat)
                    for name in names:
                        name_str = str(name)
                        try:
                            found, source_path = source_getter(mat, name_str)
                            if found:
                                result["parameter_sources"].append({
                                    "name": name_str,
                                    "type": ptype,
                                    "source": str(source_path),
                                })
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        return json.dumps(result)
    except Exception as exc:
        return _error_json(exc)
```

**Step 3: Add `inspect_function(asset_path, function_name=None)` function**

```python
# ---------------------------------------------------------------------------
# 8. inspect_function
# ---------------------------------------------------------------------------

def inspect_function(asset_path, function_name=None):
    """Return JSON with the contents of a material function.

    Two modes:
    - If function_name is given, asset_path is a material and function_name
      is a MaterialFunctionCall expression name — we find its referenced function.
    - If function_name is None, asset_path IS the material function asset path.
    """
    try:
        if function_name is not None:
            # Mode 1: find function from material's expression
            mat = _load_material(asset_path)
            full_path = _full_object_path(asset_path)
            if not function_name.startswith("MaterialExpression"):
                function_name = f"MaterialExpression{function_name}"
            expr = unreal.find_object(None, f"{full_path}:{function_name}")
            if expr is None:
                return _error_json(f"Expression not found: {function_name}")
            try:
                fn = expr.get_editor_property("material_function")
                if fn is None:
                    return _error_json(f"No material function referenced by {function_name}")
                func_path = fn.get_path_name()
            except Exception as exc:
                return _error_json(f"Cannot get function from {function_name}: {exc}")
        else:
            # Mode 2: direct function path
            func_path = asset_path
            fn = _eal().load_asset(func_path)
            if fn is None:
                return _error_json(f"Material function not found: {func_path}")

        mel = _mel()

        # Get function metadata
        info = {
            "success": True,
            "function_path": func_path,
        }
        try:
            info["description"] = str(fn.get_editor_property("description") or "")
        except Exception:
            info["description"] = ""
        try:
            info["user_exposed_caption"] = str(fn.get_editor_property("user_exposed_caption") or "")
        except Exception:
            info["user_exposed_caption"] = ""
        try:
            info["expose_to_library"] = bool(fn.get_editor_property("expose_to_library"))
        except Exception:
            pass

        # Get expression count
        try:
            info["expression_count"] = int(mel.get_num_material_expressions_in_function(fn))
        except Exception:
            info["expression_count"] = -1

        # Scan expressions inside the function using find_object
        func_full_path = _full_object_path(func_path)
        expressions = []
        found_count = 0
        target_count = info["expression_count"]

        for cls_name in KNOWN_EXPRESSION_CLASSES:
            consecutive_misses = 0
            for i in range(200):
                obj_path = f"{func_full_path}:MaterialExpression{cls_name}_{i}"
                expr = unreal.find_object(None, obj_path)
                if expr is None:
                    consecutive_misses += 1
                    if consecutive_misses >= 30:
                        break
                    continue
                consecutive_misses = 0
                found_count += 1
                entry = {
                    "class": cls_name,
                    "index": i,
                    "name": _expr_id(expr),
                }
                entry.update(_extract_expression_props(expr, cls_name))
                expressions.append(entry)
                if 0 < target_count <= found_count:
                    break
            if 0 < target_count <= found_count:
                break

        info["found_expression_count"] = found_count
        info["expressions"] = expressions

        # Separate inputs and outputs for convenience
        info["inputs"] = [e for e in expressions if e["class"] == "FunctionInput"]
        info["outputs"] = [e for e in expressions if e["class"] == "FunctionOutput"]

        return json.dumps(info)
    except Exception as exc:
        return _error_json(exc)
```

**Step 4: Add `get_instance_chain(asset_path)` function**

```python
# ---------------------------------------------------------------------------
# 9. get_instance_chain
# ---------------------------------------------------------------------------

def get_instance_chain(asset_path):
    """Return JSON with the full parent chain and child instances."""
    try:
        mat = _load_material(asset_path)
        mel = _mel()

        result = {
            "success": True,
            "asset_path": asset_path,
            "chain": [],
            "children": [],
        }

        # Walk parent chain
        current = mat
        visited = set()
        while current is not None:
            current_path = current.get_path_name()
            if current_path in visited:
                break
            visited.add(current_path)

            level = {
                "asset_path": current_path,
                "class": current.get_class().get_name(),
            }

            if isinstance(current, unreal.MaterialInstanceConstant):
                # Get overridden parameters at this level
                overrides = []
                for ptype, getter in [
                    ("Scalar", mel.get_material_instance_scalar_parameter_value),
                    ("Vector", mel.get_material_instance_vector_parameter_value),
                    ("StaticSwitch", mel.get_material_instance_static_switch_parameter_value),
                ]:
                    try:
                        name_getter = {
                            "Scalar": mel.get_scalar_parameter_names,
                            "Vector": mel.get_vector_parameter_names,
                            "StaticSwitch": mel.get_static_switch_parameter_names,
                        }[ptype]
                        names = name_getter(current)
                        for name in names:
                            name_str = str(name)
                            try:
                                val = getter(current, name_str)
                                if ptype == "Vector":
                                    val = {"r": val.r, "g": val.g, "b": val.b, "a": val.a}
                                elif ptype == "Scalar":
                                    val = float(val)
                                else:
                                    val = bool(val)
                                overrides.append({"name": name_str, "type": ptype, "value": val})
                            except Exception:
                                pass
                    except Exception:
                        pass

                # Texture params
                try:
                    tex_names = mel.get_texture_parameter_names(current)
                    for name in tex_names:
                        name_str = str(name)
                        try:
                            tex = mel.get_material_instance_texture_parameter_value(current, name_str)
                            overrides.append({
                                "name": name_str,
                                "type": "Texture",
                                "value": tex.get_path_name() if tex else None,
                            })
                        except Exception:
                            pass
                except Exception:
                    pass

                level["overrides"] = overrides

                # Walk to parent
                try:
                    parent = current.get_editor_property("parent")
                    current = parent
                except Exception:
                    current = None
            else:
                # Base material — end of chain
                level["is_root"] = True
                try:
                    level["blend_mode"] = _safe_enum_name(current.get_editor_property("blend_mode"))
                    level["shading_model"] = _safe_enum_name(current.get_editor_property("shading_model"))
                except Exception:
                    pass
                current = None

            result["chain"].append(level)

        # Get child instances of the original asset
        try:
            children = mel.get_child_instances(mat)
            for child_data in children:
                try:
                    result["children"].append({
                        "asset_path": str(child_data.package_name),
                        "asset_name": str(child_data.asset_name),
                    })
                except Exception:
                    pass
        except Exception:
            pass

        return json.dumps(result)
    except Exception as exc:
        return _error_json(exc)
```

**Step 5: Add `compare_materials(path_a, path_b)` function**

```python
# ---------------------------------------------------------------------------
# 10. compare_materials
# ---------------------------------------------------------------------------

def compare_materials(path_a, path_b):
    """Return JSON diff of two materials/instances."""
    try:
        mat_a = _load_material(path_a)
        mat_b = _load_material(path_b)

        result = {
            "success": True,
            "path_a": path_a,
            "path_b": path_b,
            "parameter_diff": {"only_a": [], "only_b": [], "changed": []},
            "property_diff": [],
            "stats_diff": {},
            "expression_diff": {},
        }

        # Compare parameters
        params_a = json.loads(get_all_parameters(path_a))
        params_b = json.loads(get_all_parameters(path_b))

        map_a = {}
        if params_a.get("success"):
            for p in params_a.get("parameters", []):
                map_a[p["name"]] = p
        map_b = {}
        if params_b.get("success"):
            for p in params_b.get("parameters", []):
                map_b[p["name"]] = p

        for name in sorted(set(map_a) | set(map_b)):
            if name in map_a and name not in map_b:
                result["parameter_diff"]["only_a"].append({"name": name, "type": map_a[name].get("type"), "default": map_a[name].get("default")})
            elif name in map_b and name not in map_a:
                result["parameter_diff"]["only_b"].append({"name": name, "type": map_b[name].get("type"), "default": map_b[name].get("default")})
            else:
                da = map_a[name].get("default")
                db = map_b[name].get("default")
                if da != db:
                    result["parameter_diff"]["changed"].append({"name": name, "type": map_a[name].get("type"), "value_a": da, "value_b": db})

        # Compare properties (only for base materials)
        is_a_base = not _is_material_instance(mat_a)
        is_b_base = not _is_material_instance(mat_b)
        if is_a_base and is_b_base:
            for prop_name in ("blend_mode", "shading_model", "material_domain", "two_sided"):
                try:
                    va = _safe_enum_name(mat_a.get_editor_property(prop_name)) if prop_name != "two_sided" else bool(mat_a.get_editor_property(prop_name))
                    vb = _safe_enum_name(mat_b.get_editor_property(prop_name)) if prop_name != "two_sided" else bool(mat_b.get_editor_property(prop_name))
                    if va != vb:
                        result["property_diff"].append({"property": prop_name, "value_a": va, "value_b": vb})
                except Exception:
                    pass

            # Compare stats
            mel = _mel()
            try:
                sa = mel.get_statistics(mat_a)
                sb = mel.get_statistics(mat_b)
                for attr in ("num_pixel_shader_instructions", "num_vertex_shader_instructions", "num_samplers"):
                    va = int(getattr(sa, attr))
                    vb = int(getattr(sb, attr))
                    if va != vb:
                        result["stats_diff"][attr] = {"a": va, "b": vb}
            except Exception:
                pass

            # Compare expression counts by class
            scan_a = json.loads(scan_all_expressions(path_a))
            scan_b = json.loads(scan_all_expressions(path_b))
            counts_a = {}
            counts_b = {}
            if scan_a.get("success"):
                for e in scan_a.get("expressions", []):
                    cls = e.get("class", "")
                    counts_a[cls] = counts_a.get(cls, 0) + 1
            if scan_b.get("success"):
                for e in scan_b.get("expressions", []):
                    cls = e.get("class", "")
                    counts_b[cls] = counts_b.get(cls, 0) + 1
            for cls in sorted(set(counts_a) | set(counts_b)):
                ca = counts_a.get(cls, 0)
                cb = counts_b.get(cls, 0)
                if ca != cb:
                    result["expression_diff"][cls] = {"a": ca, "b": cb}

        return json.dumps(result)
    except Exception as exc:
        return _error_json(exc)
```

**Step 6: Commit**

```bash
git add src/unreal_material_mcp/helpers/material_helpers.py
git commit -m "feat: add 5 read-only helper functions (stats, deps, function, chain, compare)"
```

---

### Task 2: Group A Server Tools + Tests

Add 5 new `@mcp.tool()` functions in `server.py` and corresponding tests in `test_server.py`.

**Files:**
- Modify: `src/unreal_material_mcp/server.py`
- Modify: `tests/test_server.py`

**Step 1: Update server description**

Change the `FastMCP` instructions string to mention all capabilities (not just read-only).

```python
mcp = FastMCP(
    "unreal-material",
    instructions=(
        "Provides intelligence and editing tools for Unreal Engine material graphs. "
        "Use these tools to inspect material properties, parameters, node graphs, "
        "search for materials, analyze performance, compare materials, "
        "edit material instances, and modify material graphs in an Unreal project."
    ),
)
```

**Step 2: Add `get_material_stats` tool to server.py**

Append after the `search_materials` tool:

```python
# ---------------------------------------------------------------------------
# Tool 6: get_material_stats
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_stats(asset_path: str) -> str:
    """Get shader statistics and diagnostic warnings for a material.

    Returns instruction counts, sampler usage, texture samples, and warnings
    about potential issues (high sampler count, disconnected expressions, etc.).

    Args:
        asset_path: Unreal asset path to a base Material (not an instance)
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
        f"  Shader Instructions: VS={stats.get('vertex_shader_instructions', '?')} PS={stats.get('pixel_shader_instructions', '?')}",
        f"  Samplers: {stats.get('num_samplers', '?')}",
        f"  Texture Samples: pixel={stats.get('pixel_texture_samples', '?')} vertex={stats.get('vertex_texture_samples', '?')} VT={stats.get('virtual_texture_samples', '?')}",
        f"  UV Scalars: {stats.get('uv_scalars', '?')}",
        f"  Interpolator Scalars: {stats.get('interpolator_scalars', '?')}",
    ]

    warnings = data.get("warnings", [])
    if warnings:
        lines.append("  Warnings:")
        for w in warnings:
            lines.append(f"    - {w}")
    else:
        lines.append("  No warnings.")

    return "\n".join(lines)
```

**Step 3: Add `get_material_dependencies` tool to server.py**

```python
# ---------------------------------------------------------------------------
# Tool 7: get_material_dependencies
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_dependencies(asset_path: str) -> str:
    """Get textures, material functions, and parameter sources for a material.

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
    for t in textures:
        lines.append(f"    {t}")
    if not textures:
        lines.append("    (none)")

    functions = data.get("material_functions", [])
    lines.append(f"  Material Functions ({len(functions)}):")
    for f in functions:
        lines.append(f"    {f.get('expression', '?')} -> {f.get('function_path', '?')}")
    if not functions:
        lines.append("    (none)")

    sources = data.get("parameter_sources", [])
    lines.append(f"  Parameter Sources ({len(sources)}):")
    for s in sources:
        lines.append(f"    {s.get('name', '?')} ({s.get('type', '?')}) from {s.get('source', '?')}")
    if not sources:
        lines.append("    (none)")

    return "\n".join(lines)
```

**Step 4: Add `inspect_material_function` tool to server.py**

```python
# ---------------------------------------------------------------------------
# Tool 8: inspect_material_function
# ---------------------------------------------------------------------------

@mcp.tool()
def inspect_material_function(asset_path: str, function_name: str | None = None) -> str:
    """Inspect the contents of a material function.

    Can be called two ways:
    1. With a material path + function_name (expression name like 'MaterialFunctionCall_0')
       to inspect a function referenced by that material.
    2. With a material function asset path directly (function_name=None).

    Args:
        asset_path: Material or MaterialFunction asset path
        function_name: Optional expression name of a MaterialFunctionCall node
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
        f"Function: {data.get('function_path', '?')}",
    ]
    if data.get("description"):
        lines.append(f"  Description: {data['description']}")
    if data.get("user_exposed_caption"):
        lines.append(f"  Caption: {data['user_exposed_caption']}")

    found = data.get("found_expression_count", 0)
    expected = data.get("expression_count", -1)
    lines.append(f"  Expressions: {found} found / {expected} expected")

    inputs = data.get("inputs", [])
    lines.append(f"  Inputs ({len(inputs)}):")
    for inp in inputs:
        lines.append(f"    {inp.get('name', '?')}")

    outputs = data.get("outputs", [])
    lines.append(f"  Outputs ({len(outputs)}):")
    for out in outputs:
        lines.append(f"    {out.get('name', '?')}")

    # Show all expression classes
    expressions = data.get("expressions", [])
    groups: dict[str, list] = {}
    for expr in expressions:
        cls = expr.get("class", "Unknown")
        if cls in ("FunctionInput", "FunctionOutput"):
            continue  # Already shown above
        groups.setdefault(cls, []).append(expr)

    if groups:
        lines.append("  Expression Graph:")
        for cls in sorted(groups):
            items = groups[cls]
            lines.append(f"    [{cls}] ({len(items)})")
            for expr in items:
                pos = expr.get("position", {})
                parts = [f"{expr.get('name', '?')} @ ({pos.get('x', 0)}, {pos.get('y', 0)})"]
                if "parameter_name" in expr:
                    parts.append(f"param={expr['parameter_name']}")
                if "function" in expr:
                    parts.append(f"function={expr['function']}")
                lines.append(f"      {' | '.join(parts)}")

    return "\n".join(lines)
```

**Step 5: Add `get_material_instance_chain` tool to server.py**

```python
# ---------------------------------------------------------------------------
# Tool 9: get_material_instance_chain
# ---------------------------------------------------------------------------

@mcp.tool()
def get_material_instance_chain(asset_path: str) -> str:
    """Walk the parent chain of a material instance to the root material.

    Shows overridden parameters at each level and lists child instances.

    Args:
        asset_path: Unreal asset path to a Material or MaterialInstanceConstant
    """
    script = (
        f"result = material_helpers.get_instance_chain('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [f"Instance Chain for: {data.get('asset_path', asset_path)}"]

    chain = data.get("chain", [])
    for i, level in enumerate(chain):
        prefix = "  " * i
        path = level.get("asset_path", "?")
        cls = level.get("class", "?")
        lines.append(f"{prefix}[{i}] {path} ({cls})")

        if level.get("is_root"):
            if "blend_mode" in level:
                lines.append(f"{prefix}  Blend: {level['blend_mode']} | Shading: {level.get('shading_model', '?')}")
        else:
            overrides = level.get("overrides", [])
            if overrides:
                lines.append(f"{prefix}  Overrides ({len(overrides)}):")
                for o in overrides[:20]:
                    lines.append(f"{prefix}    {o.get('name', '?')} ({o.get('type', '?')}) = {o.get('value', '?')}")
                if len(overrides) > 20:
                    lines.append(f"{prefix}    ... and {len(overrides) - 20} more")

    children = data.get("children", [])
    if children:
        lines.append(f"  Children ({len(children)}):")
        for c in children[:20]:
            lines.append(f"    {c.get('asset_name', '?')} — {c.get('asset_path', '?')}")
        if len(children) > 20:
            lines.append(f"    ... and {len(children) - 20} more")
    else:
        lines.append("  No child instances.")

    return "\n".join(lines)
```

**Step 6: Add `compare_materials` tool to server.py**

```python
# ---------------------------------------------------------------------------
# Tool 10: compare_materials
# ---------------------------------------------------------------------------

@mcp.tool()
def compare_materials(asset_path_a: str, asset_path_b: str) -> str:
    """Compare two materials or material instances side by side.

    Shows parameter differences, property differences, stat differences,
    and expression count differences.

    Args:
        asset_path_a: First material asset path
        asset_path_b: Second material asset path
    """
    script = (
        f"result = material_helpers.compare_materials("
        f"'{_escape_py_string(asset_path_a)}', "
        f"'{_escape_py_string(asset_path_b)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Comparing:",
        f"  A: {data.get('path_a', asset_path_a)}",
        f"  B: {data.get('path_b', asset_path_b)}",
    ]

    pdiff = data.get("parameter_diff", {})
    only_a = pdiff.get("only_a", [])
    only_b = pdiff.get("only_b", [])
    changed = pdiff.get("changed", [])

    if only_a or only_b or changed:
        lines.append("  Parameter Differences:")
        for p in only_a:
            lines.append(f"    - {p['name']} ({p.get('type', '?')}): only in A = {p.get('default', '?')}")
        for p in only_b:
            lines.append(f"    + {p['name']} ({p.get('type', '?')}): only in B = {p.get('default', '?')}")
        for p in changed:
            lines.append(f"    ~ {p['name']} ({p.get('type', '?')}): A={p.get('value_a', '?')} -> B={p.get('value_b', '?')}")
    else:
        lines.append("  Parameters: identical")

    prop_diff = data.get("property_diff", [])
    if prop_diff:
        lines.append("  Property Differences:")
        for p in prop_diff:
            lines.append(f"    {p['property']}: A={p.get('value_a', '?')} -> B={p.get('value_b', '?')}")

    stats_diff = data.get("stats_diff", {})
    if stats_diff:
        lines.append("  Stats Differences:")
        for attr, vals in stats_diff.items():
            lines.append(f"    {attr}: A={vals.get('a', '?')} -> B={vals.get('b', '?')}")

    expr_diff = data.get("expression_diff", {})
    if expr_diff:
        lines.append("  Expression Count Differences:")
        for cls, vals in sorted(expr_diff.items()):
            lines.append(f"    {cls}: A={vals.get('a', 0)} -> B={vals.get('b', 0)}")

    return "\n".join(lines)
```

**Step 7: Add tests for all 5 read-only tools**

Append to `tests/test_server.py`:

```python
# ---------------------------------------------------------------------------
# Tool 6: get_material_stats
# ---------------------------------------------------------------------------

class TestGetMaterialStats:
    """Output formatting tests for get_material_stats."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_stats_with_warnings(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "stats": {
                "vertex_shader_instructions": 50,
                "pixel_shader_instructions": 600,
                "num_samplers": 18,
                "vertex_texture_samples": 0,
                "pixel_texture_samples": 12,
                "virtual_texture_samples": 2,
                "uv_scalars": 4,
                "interpolator_scalars": 8,
            },
            "warnings": [
                "High sampler count: 18 (platform limit is typically 16)",
                "High pixel shader instructions: 600 (may cause performance issues)",
            ],
        })
        result = server.get_material_stats("/Game/M_Foo")

        assert "VS=50 PS=600" in result
        assert "Samplers: 18" in result
        assert "Warnings:" in result
        assert "High sampler count" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_no_warnings(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Simple",
            "stats": {
                "vertex_shader_instructions": 10,
                "pixel_shader_instructions": 30,
                "num_samplers": 2,
                "vertex_texture_samples": 0,
                "pixel_texture_samples": 2,
                "virtual_texture_samples": 0,
                "uv_scalars": 2,
                "interpolator_scalars": 4,
            },
            "warnings": [],
        })
        result = server.get_material_stats("/Game/M_Simple")

        assert "No warnings" in result


# ---------------------------------------------------------------------------
# Tool 7: get_material_dependencies
# ---------------------------------------------------------------------------

class TestGetMaterialDependencies:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_dependencies(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "textures": ["/Game/T_Diff", "/Game/T_Normal"],
            "material_functions": [
                {"expression": "MaterialFunctionCall_0", "function_path": "/Engine/Functions/MF_Fresnel"},
            ],
            "parameter_sources": [
                {"name": "Roughness", "type": "Scalar", "source": "/Game/M_Foo"},
            ],
        })
        result = server.get_material_dependencies("/Game/M_Foo")

        assert "Textures (2)" in result
        assert "/Game/T_Diff" in result
        assert "Material Functions (1)" in result
        assert "MF_Fresnel" in result
        assert "Parameter Sources (1)" in result
        assert "Roughness" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_empty_dependencies(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Empty",
            "textures": [],
            "material_functions": [],
            "parameter_sources": [],
        })
        result = server.get_material_dependencies("/Game/M_Empty")

        assert "(none)" in result


# ---------------------------------------------------------------------------
# Tool 8: inspect_material_function
# ---------------------------------------------------------------------------

class TestInspectMaterialFunction:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_function(self, _src):
        _setup_tool_mock({
            "success": True,
            "function_path": "/Engine/Functions/MF_Fresnel",
            "description": "A fresnel effect function",
            "user_exposed_caption": "Fresnel",
            "expression_count": 5,
            "found_expression_count": 5,
            "inputs": [{"class": "FunctionInput", "name": "FunctionInput_0"}],
            "outputs": [{"class": "FunctionOutput", "name": "FunctionOutput_0"}],
            "expressions": [
                {"class": "FunctionInput", "name": "FunctionInput_0", "position": {"x": 0, "y": 0}},
                {"class": "FunctionOutput", "name": "FunctionOutput_0", "position": {"x": 400, "y": 0}},
                {"class": "Fresnel", "name": "Fresnel_0", "position": {"x": 200, "y": 0}},
            ],
        })
        result = server.inspect_material_function("/Engine/Functions/MF_Fresnel")

        assert "MF_Fresnel" in result
        assert "fresnel effect" in result
        assert "Inputs (1)" in result
        assert "Outputs (1)" in result
        assert "[Fresnel]" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_expression_not_found(self, _src):
        _setup_tool_mock({"success": False, "error": "Expression not found: MaterialFunctionCall_99"})
        result = server.inspect_material_function("/Game/M_Foo", function_name="MaterialFunctionCall_99")

        assert "Error:" in result


# ---------------------------------------------------------------------------
# Tool 9: get_material_instance_chain
# ---------------------------------------------------------------------------

class TestGetMaterialInstanceChain:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_chain(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/MI_Foo",
            "chain": [
                {
                    "asset_path": "/Game/MI_Foo",
                    "class": "MaterialInstanceConstant",
                    "overrides": [
                        {"name": "Roughness", "type": "Scalar", "value": 0.8},
                    ],
                },
                {
                    "asset_path": "/Game/M_Base",
                    "class": "Material",
                    "is_root": True,
                    "blend_mode": "BLEND_OPAQUE",
                    "shading_model": "MSM_DEFAULT_LIT",
                },
            ],
            "children": [],
        })
        result = server.get_material_instance_chain("/Game/MI_Foo")

        assert "[0]" in result
        assert "MI_Foo" in result
        assert "Roughness" in result
        assert "0.8" in result
        assert "[1]" in result
        assert "M_Base" in result
        assert "is_root" not in result  # Should not expose raw key
        assert "BLEND_OPAQUE" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_with_children(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Base",
            "chain": [
                {"asset_path": "/Game/M_Base", "class": "Material", "is_root": True, "blend_mode": "BLEND_OPAQUE", "shading_model": "MSM_DEFAULT_LIT"},
            ],
            "children": [
                {"asset_path": "/Game/MI_Child1", "asset_name": "MI_Child1"},
                {"asset_path": "/Game/MI_Child2", "asset_name": "MI_Child2"},
            ],
        })
        result = server.get_material_instance_chain("/Game/M_Base")

        assert "Children (2)" in result
        assert "MI_Child1" in result
        assert "MI_Child2" in result


# ---------------------------------------------------------------------------
# Tool 10: compare_materials
# ---------------------------------------------------------------------------

class TestCompareMaterials:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_diff(self, _src):
        _setup_tool_mock({
            "success": True,
            "path_a": "/Game/M_A",
            "path_b": "/Game/M_B",
            "parameter_diff": {
                "only_a": [{"name": "Metallic", "type": "Scalar", "default": 0.0}],
                "only_b": [{"name": "Emissive", "type": "Scalar", "default": 1.0}],
                "changed": [{"name": "Roughness", "type": "Scalar", "value_a": 0.5, "value_b": 0.8}],
            },
            "property_diff": [{"property": "two_sided", "value_a": False, "value_b": True}],
            "stats_diff": {"num_samplers": {"a": 4, "b": 8}},
            "expression_diff": {"Add": {"a": 3, "b": 5}},
        })
        result = server.compare_materials("/Game/M_A", "/Game/M_B")

        assert "- Metallic" in result  # only in A
        assert "+ Emissive" in result  # only in B
        assert "~ Roughness" in result  # changed
        assert "0.5" in result
        assert "0.8" in result
        assert "two_sided" in result
        assert "num_samplers" in result
        assert "Add:" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_identical_materials(self, _src):
        _setup_tool_mock({
            "success": True,
            "path_a": "/Game/M_Same",
            "path_b": "/Game/M_Same",
            "parameter_diff": {"only_a": [], "only_b": [], "changed": []},
            "property_diff": [],
            "stats_diff": {},
            "expression_diff": {},
        })
        result = server.compare_materials("/Game/M_Same", "/Game/M_Same")

        assert "identical" in result
```

**Step 8: Run tests**

Run: `cd /c/Projects/unreal-material-mcp && uv run pytest tests/ -v`
Expected: All tests pass (14 existing + 10 new = 24 total)

**Step 9: Commit**

```bash
git add src/unreal_material_mcp/server.py tests/test_server.py
git commit -m "feat: add 5 read-only tools (stats, dependencies, function, chain, compare)"
```

---

### Task 3: Group B — Instance Editing

Add `set_instance_parameter` helper and `set_material_instance_parameter` server tool with tests.

**Files:**
- Modify: `src/unreal_material_mcp/helpers/material_helpers.py`
- Modify: `src/unreal_material_mcp/server.py`
- Modify: `tests/test_server.py`

**Step 1: Add `set_instance_parameter` to helper**

```python
# ---------------------------------------------------------------------------
# 11. set_instance_parameter
# ---------------------------------------------------------------------------

def set_instance_parameter(asset_path, parameter_name, value, parameter_type=None):
    """Set a parameter override on a MaterialInstanceConstant. Returns JSON."""
    try:
        mat = _load_material(asset_path)
        if not _is_material_instance(mat):
            return _error_json("set_instance_parameter requires a MaterialInstanceConstant, not a base Material")

        mel = _mel()

        # Auto-detect type if not provided
        if parameter_type is None:
            for ptype, getter in [
                ("Scalar", mel.get_scalar_parameter_names),
                ("Vector", mel.get_vector_parameter_names),
                ("Texture", mel.get_texture_parameter_names),
                ("StaticSwitch", mel.get_static_switch_parameter_names),
            ]:
                try:
                    names = [str(n) for n in getter(mat)]
                    if parameter_name in names:
                        parameter_type = ptype
                        break
                except Exception:
                    pass
            if parameter_type is None:
                return _error_json(f"Parameter not found: {parameter_name}")

        result = {
            "success": True,
            "asset_path": asset_path,
            "parameter_name": parameter_name,
            "parameter_type": parameter_type,
        }

        if parameter_type == "Scalar":
            try:
                old_val = float(mel.get_material_instance_scalar_parameter_value(mat, parameter_name))
            except Exception:
                old_val = None
            new_val = float(value)
            mel.set_material_instance_scalar_parameter_value(mat, parameter_name, new_val)
            result["old_value"] = old_val
            result["new_value"] = new_val

        elif parameter_type == "Vector":
            try:
                old = mel.get_material_instance_vector_parameter_value(mat, parameter_name)
                old_val = {"r": old.r, "g": old.g, "b": old.b, "a": old.a}
            except Exception:
                old_val = None
            if isinstance(value, dict):
                color = unreal.LinearColor(
                    r=float(value.get("r", 0)),
                    g=float(value.get("g", 0)),
                    b=float(value.get("b", 0)),
                    a=float(value.get("a", 1)),
                )
            else:
                return _error_json("Vector value must be a dict with r/g/b/a keys")
            mel.set_material_instance_vector_parameter_value(mat, parameter_name, color)
            result["old_value"] = old_val
            result["new_value"] = {"r": color.r, "g": color.g, "b": color.b, "a": color.a}

        elif parameter_type == "Texture":
            try:
                old_tex = mel.get_material_instance_texture_parameter_value(mat, parameter_name)
                old_val = old_tex.get_path_name() if old_tex else None
            except Exception:
                old_val = None
            tex_path = str(value)
            new_tex = _eal().load_asset(tex_path)
            if new_tex is None:
                return _error_json(f"Texture not found: {tex_path}")
            mel.set_material_instance_texture_parameter_value(mat, parameter_name, new_tex)
            result["old_value"] = old_val
            result["new_value"] = tex_path

        elif parameter_type == "StaticSwitch":
            try:
                old_val = bool(mel.get_material_instance_static_switch_parameter_value(mat, parameter_name))
            except Exception:
                old_val = None
            new_val = bool(value)
            mel.set_material_instance_static_switch_parameter_value(mat, parameter_name, new_val)
            result["old_value"] = old_val
            result["new_value"] = new_val

        else:
            return _error_json(f"Unknown parameter type: {parameter_type}")

        # Update the instance
        mel.update_material_instance(mat)

        return json.dumps(result)
    except Exception as exc:
        return _error_json(exc)
```

**Step 2: Add `set_material_instance_parameter` tool to server.py**

```python
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
    """Set a parameter override on a MaterialInstanceConstant.

    Args:
        asset_path: Path to a MaterialInstanceConstant
        parameter_name: Name of the parameter to set
        value: New value. For Scalar: number string. For Vector: JSON like '{"r":1,"g":0,"b":0,"a":1}'.
               For Texture: asset path string. For StaticSwitch: 'true' or 'false'.
        parameter_type: Optional type hint: 'Scalar', 'Vector', 'Texture', or 'StaticSwitch'.
                        Auto-detected if omitted.
    """
    # Parse value based on type
    type_arg = f"'{_escape_py_string(parameter_type)}'" if parameter_type else "None"

    # For vector values, pass the JSON dict directly
    # For other types, pass the raw string and let the helper parse it
    try:
        parsed_value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        parsed_value = value

    value_repr = json.dumps(parsed_value)

    script = (
        f"result = material_helpers.set_instance_parameter("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(parameter_name)}', "
        f"{value_repr}, "
        f"parameter_type={type_arg})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Material Instance: {data.get('asset_path', asset_path)}",
        f"  Parameter: {data.get('parameter_name', parameter_name)} ({data.get('parameter_type', '?')})",
        f"  Old Value: {data.get('old_value', '?')}",
        f"  New Value: {data.get('new_value', '?')}",
        f"  Updated successfully.",
    ]
    return "\n".join(lines)
```

**Step 3: Add tests**

```python
# ---------------------------------------------------------------------------
# Tool 11: set_material_instance_parameter
# ---------------------------------------------------------------------------

class TestSetMaterialInstanceParameter:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_scalar_update(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/MI_Foo",
            "parameter_name": "Roughness",
            "parameter_type": "Scalar",
            "old_value": 0.5,
            "new_value": 0.8,
        })
        result = server.set_material_instance_parameter("/Game/MI_Foo", "Roughness", "0.8", "Scalar")

        assert "Roughness" in result
        assert "0.5" in result
        assert "0.8" in result
        assert "Updated successfully" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_not_instance(self, _src):
        _setup_tool_mock({
            "success": False,
            "error": "set_instance_parameter requires a MaterialInstanceConstant, not a base Material",
        })
        result = server.set_material_instance_parameter("/Game/M_Base", "Roughness", "0.5")

        assert "Error:" in result
        assert "MaterialInstanceConstant" in result
```

**Step 4: Run tests, commit**

```bash
cd /c/Projects/unreal-material-mcp && uv run pytest tests/ -v
git add src/unreal_material_mcp/helpers/material_helpers.py src/unreal_material_mcp/server.py tests/test_server.py
git commit -m "feat: add set_material_instance_parameter tool for MI editing"
```

---

### Task 4: Group C Helper Functions (6 graph editing)

Add 6 write helper functions to `material_helpers.py`.

**Files:**
- Modify: `src/unreal_material_mcp/helpers/material_helpers.py`

**Step 1: Add `create_expression` function**

```python
# ---------------------------------------------------------------------------
# 12. create_expression
# ---------------------------------------------------------------------------

def create_expression(asset_path, expression_class, node_pos_x=0, node_pos_y=0, properties=None):
    """Create a new material expression node. Returns JSON with created name."""
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot edit: asset is a MaterialInstanceConstant, not a Material")

        mel = _mel()

        # Resolve the expression class
        full_class_name = f"MaterialExpression{expression_class}"
        expr_class = getattr(unreal, full_class_name, None)
        if expr_class is None:
            return _error_json(f"Expression class not found: {full_class_name}")

        # Create the expression
        expr = mel.create_material_expression(mat, expr_class, int(node_pos_x), int(node_pos_y))
        if expr is None:
            return _error_json(f"Failed to create expression of type {expression_class}")

        # Set optional properties
        if properties:
            for prop_name, prop_value in properties.items():
                try:
                    expr.set_editor_property(prop_name, prop_value)
                except Exception:
                    pass  # Best effort — some properties may not exist

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "expression_name": _expr_id(expr),
            "expression_class": expression_class,
            "position": {"x": int(node_pos_x), "y": int(node_pos_y)},
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 2: Add `delete_expression` function**

```python
# ---------------------------------------------------------------------------
# 13. delete_expression
# ---------------------------------------------------------------------------

def delete_expression(asset_path, expression_name):
    """Delete a material expression by name. Returns JSON."""
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot edit: asset is a MaterialInstanceConstant, not a Material")

        mel = _mel()
        full_path = _full_object_path(asset_path)

        if not expression_name.startswith("MaterialExpression"):
            expression_name = f"MaterialExpression{expression_name}"

        expr = unreal.find_object(None, f"{full_path}:{expression_name}")
        if expr is None:
            return _error_json(f"Expression not found: {expression_name}")

        mel.delete_material_expression(mat, expr)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "deleted": expression_name,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 3: Add `connect_expressions` function**

```python
# ---------------------------------------------------------------------------
# 14. connect_expressions
# ---------------------------------------------------------------------------

# Map of human-friendly property names to EMaterialProperty enum values
_PROPERTY_NAME_MAP = {p[0].lower(): p[1] for p in _MATERIAL_PROPERTIES}

def connect_expressions(asset_path, from_expression, to_expression_or_property,
                        from_output="", to_input=""):
    """Connect two expressions, or connect an expression to a material output pin."""
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot edit: asset is a MaterialInstanceConstant, not a Material")

        mel = _mel()
        full_path = _full_object_path(asset_path)

        # Resolve from expression
        from_name = from_expression
        if not from_name.startswith("MaterialExpression"):
            from_name = f"MaterialExpression{from_name}"
        from_expr = unreal.find_object(None, f"{full_path}:{from_name}")
        if from_expr is None:
            return _error_json(f"From expression not found: {from_name}")

        # Check if target is a material property
        target_lower = to_expression_or_property.lower()
        if target_lower in _PROPERTY_NAME_MAP:
            prop_attr = _PROPERTY_NAME_MAP[target_lower]
            prop_enum = getattr(unreal.MaterialProperty, prop_attr)
            success = mel.connect_material_property(from_expr, from_output, prop_enum)
            return json.dumps({
                "success": success,
                "asset_path": asset_path,
                "connection": f"{from_expression}[{from_output or 'default'}] -> {to_expression_or_property}",
                "type": "property",
            })

        # Otherwise it's expression-to-expression
        to_name = to_expression_or_property
        if not to_name.startswith("MaterialExpression"):
            to_name = f"MaterialExpression{to_name}"
        to_expr = unreal.find_object(None, f"{full_path}:{to_name}")
        if to_expr is None:
            return _error_json(f"To expression not found: {to_name}")

        success = mel.connect_material_expressions(from_expr, from_output, to_expr, to_input)
        return json.dumps({
            "success": success,
            "asset_path": asset_path,
            "connection": f"{from_expression}[{from_output or 'default'}] -> {to_expression_or_property}[{to_input or 'default'}]",
            "type": "expression",
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 4: Add `set_property` function**

```python
# ---------------------------------------------------------------------------
# 15. set_property
# ---------------------------------------------------------------------------

def set_property(asset_path, property_name, value):
    """Set a top-level material property (blend_mode, shading_model, etc.)."""
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot edit: asset is a MaterialInstanceConstant, not a Material")

        mel = _mel()
        result = {"success": True, "asset_path": asset_path, "property": property_name}

        prop_lower = property_name.lower()

        if prop_lower == "blend_mode":
            old = _safe_enum_name(mat.get_editor_property("blend_mode"))
            enum_val = getattr(unreal.BlendMode, str(value).upper(), None)
            if enum_val is None:
                return _error_json(f"Unknown blend mode: {value}")
            mat.set_editor_property("blend_mode", enum_val)
            result["old_value"] = old
            result["new_value"] = str(value).upper()

        elif prop_lower == "shading_model":
            old = _safe_enum_name(mat.get_editor_property("shading_model"))
            enum_val = getattr(unreal.MaterialShadingModel, str(value).upper(), None)
            if enum_val is None:
                return _error_json(f"Unknown shading model: {value}")
            mat.set_editor_property("shading_model", enum_val)
            result["old_value"] = old
            result["new_value"] = str(value).upper()

        elif prop_lower == "two_sided":
            old = bool(mat.get_editor_property("two_sided"))
            new_val = str(value).lower() in ("true", "1", "yes")
            mat.set_editor_property("two_sided", new_val)
            result["old_value"] = old
            result["new_value"] = new_val

        elif prop_lower == "material_domain":
            old = _safe_enum_name(mat.get_editor_property("material_domain"))
            enum_val = getattr(unreal.MaterialDomain, str(value).upper(), None)
            if enum_val is None:
                return _error_json(f"Unknown material domain: {value}")
            mat.set_editor_property("material_domain", enum_val)
            result["old_value"] = old
            result["new_value"] = str(value).upper()

        elif prop_lower.startswith("usage_"):
            usage_name = prop_lower.replace("usage_", "").upper()
            enum_val = getattr(unreal.MaterialUsage, usage_name, None)
            if enum_val is None:
                return _error_json(f"Unknown usage flag: {usage_name}")
            needs_recompile = False
            success = mel.set_material_usage(mat, enum_val, needs_recompile)
            result["set_usage"] = usage_name
            result["result"] = success

        else:
            return _error_json(f"Unknown property: {property_name}. Supported: blend_mode, shading_model, two_sided, material_domain, usage_*")

        return json.dumps(result)
    except Exception as exc:
        return _error_json(exc)
```

**Step 5: Add `recompile` and `layout_graph` functions**

```python
# ---------------------------------------------------------------------------
# 16. recompile
# ---------------------------------------------------------------------------

def recompile(asset_path):
    """Recompile a material. Returns JSON."""
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot recompile a MaterialInstanceConstant — recompile its parent Material")

        _mel().recompile_material(mat)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "recompiled": True,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# 17. layout_graph
# ---------------------------------------------------------------------------

def layout_graph(asset_path):
    """Auto-layout all expression nodes in a grid pattern. Returns JSON."""
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot layout a MaterialInstanceConstant graph")

        _mel().layout_material_expressions(mat)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "laid_out": True,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 6: Commit**

```bash
git add src/unreal_material_mcp/helpers/material_helpers.py
git commit -m "feat: add 7 write helper functions (instance param, create, delete, connect, property, recompile, layout)"
```

---

### Task 5: Group C Server Tools + Tests

Add 6 graph editing tools to `server.py` and tests.

**Files:**
- Modify: `src/unreal_material_mcp/server.py`
- Modify: `tests/test_server.py`

**Step 1: Add `create_material_expression` tool**

```python
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
        asset_path: Path to a base Material
        expression_class: Short class name without prefix (e.g. 'ScalarParameter', 'Multiply')
        node_pos_x: X position in the graph editor
        node_pos_y: Y position in the graph editor
        properties: Optional JSON dict of properties to set (e.g. '{"parameter_name": "Roughness"}')
    """
    props_repr = "None"
    if properties:
        try:
            props_repr = properties  # Already a JSON string
            json.loads(properties)  # Validate
        except json.JSONDecodeError:
            return f"Error: Invalid properties JSON: {properties}"

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

    pos = data.get("position", {})
    return (
        f"Created: {data.get('expression_name', '?')} ({data.get('expression_class', '?')})\n"
        f"  Position: ({pos.get('x', 0)}, {pos.get('y', 0)})\n"
        f"  Material: {data.get('asset_path', asset_path)}"
    )
```

**Step 2: Add `delete_material_expression` tool**

```python
# ---------------------------------------------------------------------------
# Tool 13: delete_material_expression
# ---------------------------------------------------------------------------

@mcp.tool()
def delete_material_expression(asset_path: str, expression_name: str) -> str:
    """Delete an expression node from a material graph.

    The expression will be automatically disconnected before deletion.

    Args:
        asset_path: Path to a base Material
        expression_name: Expression object name (e.g. 'MaterialExpressionAdd_0' or 'Add_0')
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

    return (
        f"Deleted: {data.get('deleted', expression_name)}\n"
        f"  Material: {data.get('asset_path', asset_path)}"
    )
```

**Step 3: Add `connect_material_expressions` tool**

```python
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
    """Connect two material expressions, or connect an expression to a material output pin.

    If to_expression_or_property is a material property name (BaseColor, Roughness, Normal, etc.),
    connects the expression to that output pin. Otherwise connects expression-to-expression.

    Args:
        asset_path: Path to a base Material
        from_expression: Source expression name (e.g. 'Multiply_0')
        to_expression_or_property: Target expression name OR material property name
        from_output: Output pin name on source (empty = first output)
        to_input: Input pin name on target (empty = first input, ignored for property connections)
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

    return (
        f"Connected: {data.get('connection', '?')}\n"
        f"  Type: {data.get('type', '?')}\n"
        f"  Material: {data.get('asset_path', asset_path)}"
    )
```

**Step 4: Add `set_material_property` tool**

```python
# ---------------------------------------------------------------------------
# Tool 15: set_material_property
# ---------------------------------------------------------------------------

@mcp.tool()
def set_material_property(asset_path: str, property_name: str, value: str) -> str:
    """Set a top-level material property.

    Supported properties: blend_mode, shading_model, two_sided, material_domain, usage_*.

    Args:
        asset_path: Path to a base Material
        property_name: Property to set (e.g. 'blend_mode', 'shading_model', 'two_sided')
        value: New value (e.g. 'TRANSLUCENT', 'UNLIT', 'true')
    """
    script = (
        f"result = material_helpers.set_property("
        f"'{_escape_py_string(asset_path)}', "
        f"'{_escape_py_string(property_name)}', "
        f"'{_escape_py_string(value)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [f"Material: {data.get('asset_path', asset_path)}"]
    if "old_value" in data:
        lines.append(f"  {data.get('property', property_name)}: {data.get('old_value', '?')} -> {data.get('new_value', '?')}")
    elif "set_usage" in data:
        lines.append(f"  Usage {data['set_usage']}: {'enabled' if data.get('result') else 'failed'}")
    return "\n".join(lines)
```

**Step 5: Add `recompile_material` and `layout_material_graph` tools**

```python
# ---------------------------------------------------------------------------
# Tool 16: recompile_material
# ---------------------------------------------------------------------------

@mcp.tool()
def recompile_material(asset_path: str) -> str:
    """Recompile a material to apply graph changes.

    Call this after making edits (create/delete/connect expressions, set properties).
    Can be deferred to batch multiple changes before recompiling.

    Args:
        asset_path: Path to a base Material
    """
    script = (
        f"result = material_helpers.recompile('{_escape_py_string(asset_path)}')\n"
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
    """Auto-layout all expression nodes in a material graph in a grid pattern.

    Useful after programmatic creation of many nodes.

    Args:
        asset_path: Path to a base Material
    """
    script = (
        f"result = material_helpers.layout_graph('{_escape_py_string(asset_path)}')\n"
        "print(result)\n"
    )
    data = _run_material_script(script)

    err = _format_error(data)
    if err:
        return f"Error: {err}"

    return f"Layout applied: {data.get('asset_path', asset_path)}"
```

**Step 6: Add tests for graph editing tools**

```python
# ---------------------------------------------------------------------------
# Tool 12: create_material_expression
# ---------------------------------------------------------------------------

class TestCreateMaterialExpression:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_created(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "expression_name": "MaterialExpressionScalarParameter_3",
            "expression_class": "ScalarParameter",
            "position": {"x": -400, "y": 200},
        })
        result = server.create_material_expression("/Game/M_Foo", "ScalarParameter", -400, 200)

        assert "ScalarParameter_3" in result
        assert "(-400, 200)" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_bad_class(self, _src):
        _setup_tool_mock({"success": False, "error": "Expression class not found: MaterialExpressionFakeNode"})
        result = server.create_material_expression("/Game/M_Foo", "FakeNode")

        assert "Error:" in result


# ---------------------------------------------------------------------------
# Tool 13: delete_material_expression
# ---------------------------------------------------------------------------

class TestDeleteMaterialExpression:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_deleted(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "deleted": "MaterialExpressionAdd_0",
        })
        result = server.delete_material_expression("/Game/M_Foo", "Add_0")

        assert "Deleted:" in result
        assert "Add_0" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_not_found(self, _src):
        _setup_tool_mock({"success": False, "error": "Expression not found: MaterialExpressionAdd_99"})
        result = server.delete_material_expression("/Game/M_Foo", "Add_99")

        assert "Error:" in result


# ---------------------------------------------------------------------------
# Tool 14: connect_material_expressions
# ---------------------------------------------------------------------------

class TestConnectMaterialExpressions:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_expression_to_expression(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "connection": "Multiply_0[default] -> Add_0[A]",
            "type": "expression",
        })
        result = server.connect_material_expressions("/Game/M_Foo", "Multiply_0", "Add_0", to_input="A")

        assert "Multiply_0" in result
        assert "Add_0" in result
        assert "expression" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_expression_to_property(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "connection": "Multiply_0[default] -> BaseColor",
            "type": "property",
        })
        result = server.connect_material_expressions("/Game/M_Foo", "Multiply_0", "BaseColor")

        assert "BaseColor" in result
        assert "property" in result


# ---------------------------------------------------------------------------
# Tool 15: set_material_property
# ---------------------------------------------------------------------------

class TestSetMaterialProperty:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_property_change(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "property": "blend_mode",
            "old_value": "BLEND_OPAQUE",
            "new_value": "BLEND_TRANSLUCENT",
        })
        result = server.set_material_property("/Game/M_Foo", "blend_mode", "BLEND_TRANSLUCENT")

        assert "BLEND_OPAQUE" in result
        assert "BLEND_TRANSLUCENT" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_bad_property(self, _src):
        _setup_tool_mock({"success": False, "error": "Unknown property: fake_prop"})
        result = server.set_material_property("/Game/M_Foo", "fake_prop", "whatever")

        assert "Error:" in result


# ---------------------------------------------------------------------------
# Tool 16-17: recompile_material, layout_material_graph
# ---------------------------------------------------------------------------

class TestRecompileAndLayout:

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_recompile(self, _src):
        _setup_tool_mock({"success": True, "asset_path": "/Game/M_Foo", "recompiled": True})
        result = server.recompile_material("/Game/M_Foo")

        assert "Recompiled" in result
        assert "/Game/M_Foo" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_layout(self, _src):
        _setup_tool_mock({"success": True, "asset_path": "/Game/M_Foo", "laid_out": True})
        result = server.layout_material_graph("/Game/M_Foo")

        assert "Layout applied" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_recompile_error_on_instance(self, _src):
        _setup_tool_mock({"success": False, "error": "Cannot recompile a MaterialInstanceConstant"})
        result = server.recompile_material("/Game/MI_Foo")

        assert "Error:" in result
```

**Step 7: Run tests, commit**

```bash
cd /c/Projects/unreal-material-mcp && uv run pytest tests/ -v
git add src/unreal_material_mcp/server.py tests/test_server.py
git commit -m "feat: add 6 graph editing tools (create, delete, connect, property, recompile, layout)"
```

---

### Task 6: Update CLAUDE.md

Update the CLAUDE.md to document all 17 tools.

**Files:**
- Modify: `C:\Projects\unreal-material-mcp\CLAUDE.md`

**Step 1: Update tool list in CLAUDE.md**

Replace the tool list section to include all 17 tools organized by group. Update the server description. Add notes about write operation patterns (recompile after graph edits, UpdateMaterialInstance after param changes).

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with all 17 tools"
```

---

### Task 7: Live Validation

Test all 12 new tools against the running UE 5.7 editor.

**Files:** None (validation only)

**Step 1: Test `get_material_stats`**

```python
from unreal_material_mcp.server import _run_material_script, _reset_state
_reset_state()
script = "result = material_helpers.get_stats('/Game/CC_Shaders/SkinShader/RL_HQSkin')\nprint(result)\n"
data = _run_material_script(script)
# Expect: stats with instruction counts, sampler count, potentially warnings
```

**Step 2: Test `get_material_dependencies`**

```python
script = "result = material_helpers.get_dependencies('/Game/CC_Shaders/SkinShader/RL_HQSkin')\nprint(result)\n"
data = _run_material_script(script)
# Expect: textures list, material_functions list (31 MaterialFunctionCalls), parameter_sources
```

**Step 3: Test `inspect_material_function`**

```python
# First find a MaterialFunctionCall, then inspect it
script = "result = material_helpers.inspect_function('/Game/CC_Shaders/SkinShader/RL_HQSkin', 'MaterialExpressionMaterialFunctionCall_0')\nprint(result)\n"
data = _run_material_script(script)
# Expect: function description, inputs, outputs, expressions inside
```

**Step 4: Test `get_material_instance_chain`**

```python
# Find a material instance first
script = "result = material_helpers.get_instance_chain('/Game/Characters/UEFN_CC5_02/Materials/Eevee_UEFN/Std_Skin_Head_HQ_Inst')\nprint(result)\n"
data = _run_material_script(script)
# Expect: chain with instance -> parent(s) -> root material, overrides at each level
```

**Step 5: Test `compare_materials`**

```python
script = "result = material_helpers.compare_materials('/DrawCallReducer/Materials/RL_LWSkin_Array_DCR', '/Game/CC_Shaders/SkinShader/RL_HQSkin')\nprint(result)\n"
data = _run_material_script(script)
# Expect: parameter diffs, expression diffs, stats diffs between the two skin shaders
```

**Step 6: Test write tools (on a test material)**

Create a fresh test material or use an expendable one. Test:
- `set_instance_parameter` on a material instance
- `create_expression` + `connect_expressions` + `recompile` workflow
- `set_property` (e.g. toggle two_sided)
- `delete_expression` on a just-created expression
- `layout_graph`

**Step 7: Fix any issues found, re-run tests, commit fixes**

```bash
cd /c/Projects/unreal-material-mcp && uv run pytest tests/ -v
git add -A && git commit -m "fix: live validation fixes for Tier 2 tools"
```

---

### Task 8: Final Review

Run full test suite, verify all 17 tools work, check for any remaining issues.

**Step 1: Run full test suite**

```bash
cd /c/Projects/unreal-material-mcp && uv run pytest tests/ -v
```

Expected: All tests pass (~36 tests).

**Step 2: Verify import and startup**

```bash
cd /c/Projects/unreal-material-mcp && uv run python -c "from unreal_material_mcp.server import mcp; print(f'Tools: {len(mcp._tool_manager._tools)}')"
```

Expected: `Tools: 17`

**Step 3: Final commit if needed**

```bash
git log --oneline
```
