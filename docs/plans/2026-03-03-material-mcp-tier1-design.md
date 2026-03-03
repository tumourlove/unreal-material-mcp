# Design: unreal-material-mcp (Tier 1 Core)

## Overview

MCP server for inspecting UE material graphs via the editor Python bridge. Tier 1 delivers 5 read-only inspection tools covering material attributes, parameters, expression graphs, connection tracing, and search.

## Decisions

- **Scope:** Focused Tier 1 core — 5 tools (info, parameters, expressions, connections, search). Diagnostics, dependencies, and material function tools deferred.
- **Expression discovery:** Brute-force scan using `find_object` with `ClassName_N` patterns across ~35 known expression classes. Use `get_num_material_expressions()` as target count for early termination.
- **Script strategy:** Helper module uploaded to `{project}/Saved/MaterialMCP/material_helpers.py`. Tools send short scripts that import it. Version hash comparison skips re-upload if unchanged.

## Architecture

Two-layer system matching sister servers:

1. **MCP server** (`server.py`) — 5 FastMCP tools, formatted string returns
2. **Editor bridge** (`editor_bridge.py`) — UE remote execution protocol (UDP multicast discovery → TCP commands), copied from blueprint server with updated import path
3. **Helper module** (`helpers/material_helpers.py`) — uploaded to editor on first use, contains all scanning/tracing logic

## Project Structure

```
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
```

## Helper Module Strategy

On first tool call, the server:
1. Reads `helpers/material_helpers.py` from the installed package
2. Writes it to `{UE_PROJECT_PATH}/Saved/MaterialMCP/material_helpers.py`
3. Prepends `sys.path.insert(0, '{saved_dir}'); import material_helpers` to each tool script
4. Version hash comparison skips re-upload if unchanged

The helper contains:
- `scan_all_expressions(asset_path)` — brute-force scan across ~35 known expression classes
- `trace_connections(asset_path, expr_name)` — recursive connection tracing
- `get_material_info(asset_path)` — material attributes
- `get_all_parameters(asset_path)` — all 4 parameter types with defaults
- `search_materials_in_path(base_path, query, filter_type)` — asset registry search

## Tools (5)

### get_material_info(asset_path)
Returns: blend mode, shading model, material domain, two-sided, usage flags, expression count.

### get_material_parameters(asset_path)
Returns: all parameters (scalar, vector, texture, static switch) with types, default values, parameter groups, sort priority.

### get_material_expressions(asset_path, class_filter?)
Returns: all expressions with class name, object name, x/y position, and key properties (parameter_name for params, mask channels for ComponentMask, HLSL code for Custom nodes, etc.). Optional class_filter narrows the scan.

### trace_material_connections(asset_path, expression_name?)
Returns: connection graph showing input pin → source expression mappings. If expression_name given, traces from that node recursively. If omitted, traces from material output pins (BaseColor, Normal, etc.).

### search_materials(path, query, filter_type?)
Returns: materials matching the query within a content path. filter_type can be: "parameter" (param name), "expression" (expression class), "shading_model". Default searches parameter names.

## Expression Discovery Details

Known expression classes (~35):
- Math: Add, Subtract, Multiply, Divide, Clamp, OneMinus, Power, Abs, Floor, Ceil, Frac, Fmod, Min, Max, Dot, CrossProduct
- Vector: ComponentMask, AppendVector, Normalize, TransformPosition, TransformVector
- Parameters: ScalarParameter, VectorParameter, TextureSampleParameter2D, TextureSampleParameter2DArray, TextureObjectParameter, StaticSwitchParameter, StaticBoolParameter
- Constants: Constant, Constant2Vector, Constant3Vector, Constant4Vector, StaticBool
- Texture: TextureSample, TextureCoordinate
- Utility: LinearInterpolate, If, Custom, MaterialFunctionCall, Comment, VertexColor, Time, Fresnel, DepthFade, WorldPosition, PixelDepth, SceneDepth, ScreenPosition

Scan algorithm:
1. `count = mel.get_num_material_expressions(mat)`
2. For each class in the list, try `_0`, `_1`, ... `_N` until `find_object` returns None
3. Track found count; stop early when found == count
4. For each found expression, extract: name, class, position (`material_expression_editor_x/y`), and class-specific properties

## Error Handling

- `EditorNotRunning` → "Editor not available: {details}"
- Helper upload failure → "Failed to upload helper to {path}: {error}"
- Expression not found → return what was found + note about missing count
- Invalid asset path → UE error propagated: "Asset not found: {path}"

## Testing

Mock-based, no editor required:
- Mock `EditorBridge.run_command` with canned JSON responses
- Test each tool's output formatting and error paths
- Test helper upload logic with mocked file I/O
- `_reset_state()` in server.py for test isolation
