# Design: unreal-material-mcp Tier 2 Expansion

## Overview

12 new tools expanding the material MCP from read-only inspection (5 tools) to full material editing and analysis (17 tools total). Organized into three groups: read-only extensions, instance editing, and graph editing.

## Decisions

- **Edit safety:** Full editing power — no guard rails or confirmation flags. Trust the AI to use tools wisely.
- **Diagnostics:** Stats from `GetStatistics()` plus basic warnings (high sampler count, disconnected expressions, unused parameters). No deep analysis or optimization suggestions.
- **Function inspection:** Read function contents (expressions, inputs/outputs, description). No function graph editing.
- **Instance chain:** Full chain walker — parent chain with overrides at each level, child instances, parameter source tracing.
- **Tool count:** Ship all 12. 17 total tools.

## New Tools

### Group A — Read-Only Extensions (5 tools)

#### `get_material_stats(asset_path)`
Calls `UMaterialEditingLibrary::GetStatistics()`. Returns:
- Vertex/pixel shader instruction counts
- Sampler count, texture sample counts (vertex/pixel/virtual)
- UV scalars, interpolator scalars

Basic warnings when thresholds exceeded:
- Samplers > 16 (platform limit)
- Pixel instructions > 500 (performance concern)
- Disconnected expressions (not connected to any output)
- Unused parameters (parameter expressions not connected to anything)

Disconnected/unused detection: scan all expressions, trace all connections from output pins, flag any expression not visited. For unused parameters specifically, check if any parameter expression has zero downstream connections.

#### `get_material_dependencies(asset_path)`
Returns:
- All textures used via `GetUsedTextures()`
- All material functions referenced — scan `MaterialFunctionCall` expressions, extract `.material_function` asset path from each
- Parameter sources — for each parameter, which asset it originates from via `Get[Scalar/Vector/Texture/StaticSwitch]ParameterSource()`

#### `inspect_material_function(asset_path, function_name?)`
Two modes:
1. **From material**: given `asset_path` (a material) + `function_name` (e.g. `MaterialExpressionMaterialFunctionCall_0`), find the expression, get its `.material_function` reference, then scan that function's graph
2. **Direct**: given `asset_path` as a MaterialFunction asset path, scan it directly

Uses `GetNumMaterialExpressionsInFunction()` + same brute-force `find_object` scan. Returns:
- Function description, user exposed caption
- Input/output nodes (`FunctionInput`/`FunctionOutput` expressions)
- All expressions within the function with class, name, position, properties

#### `get_material_instance_chain(asset_path)`
Walks parent chain from `MaterialInstanceConstant` up to root `Material`:
- At each level: asset path, class, overridden parameters with values
- Child instances via `GetChildInstances()`
- Parameter source tracing via `Get*ParameterSource()` for each overridden param

Works on both `MaterialInstanceConstant` and base `Material` (which just returns its children).

#### `compare_materials(asset_path_a, asset_path_b)`
Diffs two materials or material instances:
- Parameters: added/removed/changed values between A and B
- Expression counts by class (if both are base materials)
- Stats differences (instruction counts, sampler counts)
- Property differences (blend mode, shading model, two-sided, material domain)

### Group B — Instance Editing (1 tool)

#### `set_material_instance_parameter(asset_path, parameter_name, value, parameter_type?)`
Sets a parameter override on a `MaterialInstanceConstant`:
- **Scalar**: `SetMaterialInstanceScalarParameterValue(instance, name, float)`
- **Vector**: `SetMaterialInstanceVectorParameterValue(instance, name, LinearColor)` — value as `{"r": 1.0, "g": 0.5, "b": 0.0, "a": 1.0}`
- **Texture**: `SetMaterialInstanceTextureParameterValue(instance, name, loaded_texture)` — value is asset path string
- **StaticSwitch**: `SetMaterialInstanceStaticSwitchParameterValue(instance, name, bool)`

Auto-detects parameter type if `parameter_type` not provided (tries each getter). Calls `UpdateMaterialInstance()` after setting. Returns old and new values.

### Group C — Graph Editing (6 tools)

#### `create_material_expression(asset_path, expression_class, node_pos_x?, node_pos_y?, properties?)`
Creates a new expression node via `CreateMaterialExpression(material, class, x, y)`.
- `expression_class`: short name without prefix (e.g. `"ScalarParameter"`, `"Multiply"`)
- Position defaults to (0, 0)
- Optional `properties` dict sets values after creation (e.g. `{"parameter_name": "Roughness", "default_value": 0.5}`)
- Returns created expression's object name (e.g. `MaterialExpressionScalarParameter_3`)

#### `delete_material_expression(asset_path, expression_name)`
Deletes an expression via `DeleteMaterialExpression(material, expression)`. Auto-disconnects from other expressions. Returns success/failure.

#### `connect_material_expressions(asset_path, from_expression, to_expression_or_property, from_output?, to_input?)`
Two modes based on `to_expression_or_property`:
1. **Expression-to-expression**: when target is an expression name (e.g. `"MaterialExpressionMultiply_0"`), calls `ConnectMaterialExpressions(from, output_name, to, input_name)`. Output/input names default to first pin if omitted.
2. **Expression-to-output pin**: when target is a material property name (e.g. `"BaseColor"`, `"Roughness"`, `"Normal"`), calls `ConnectMaterialProperty(from, output_name, property_enum)`.

#### `set_material_property(asset_path, property_name, value)`
Sets top-level material properties:
- `blend_mode`: `OPAQUE`, `MASKED`, `TRANSLUCENT`, `ADDITIVE`, `MODULATE`, `ALPHA_COMPOSITE`, `ALPHA_HOLDOUT`
- `shading_model`: `DEFAULT_LIT`, `UNLIT`, `SUBSURFACE`, `SUBSURFACE_PROFILE`, `CLEAR_COAT`, `TWO_SIDED_FOLIAGE`, `HAIR`, `CLOTH`, `EYE`, `SINGLE_LAYER_WATER`, `THIN_TRANSLUCENT`
- `two_sided`: `true`/`false`
- `material_domain`: `SURFACE`, `DEFERRED_DECAL`, `LIGHT_FUNCTION`, `POST_PROCESS`, `UI`
- Usage flags via `SetMaterialUsage(material, usage_enum)` — e.g. `"SKELETAL_MESH"`, `"PARTICLE_SPRITES"`, etc.

#### `recompile_material(asset_path)`
Triggers `RecompileMaterial()`. Separate from edits so multiple changes can be batched before recompiling. Returns success.

#### `layout_material_graph(asset_path)`
Calls `LayoutMaterialExpressions()` to auto-arrange all nodes in a grid pattern. Useful after programmatic creation of many nodes.

## Helper Module Changes

All new logic goes into `helpers/material_helpers.py`. New functions:

- `get_stats(asset_path)` — GetStatistics + warning analysis
- `get_dependencies(asset_path)` — textures, functions, parameter sources
- `inspect_function(asset_path_or_func, func_name)` — function graph scan
- `get_instance_chain(asset_path)` — parent walk + children + overrides
- `compare_materials(path_a, path_b)` — diff
- `set_instance_parameter(path, name, value, type)` — MI param setter
- `create_expression(path, cls, x, y, props)` — create + set properties
- `delete_expression(path, expr_name)` — delete
- `connect_expressions(path, from, to, from_out, to_in)` — connect
- `set_property(path, prop_name, value)` — set material property
- `recompile(path)` — recompile
- `layout_graph(path)` — auto-layout

## API Surface Used

New UE APIs consumed (beyond Tier 1):

| API | Tool |
|-----|------|
| `GetStatistics()` | get_material_stats |
| `GetUsedTextures()` | get_material_dependencies |
| `Get*ParameterSource()` | get_material_dependencies, get_material_instance_chain |
| `GetChildInstances()` | get_material_instance_chain |
| `GetNumMaterialExpressionsInFunction()` | inspect_material_function |
| `Set*MaterialInstanceParameterValue()` | set_material_instance_parameter |
| `UpdateMaterialInstance()` | set_material_instance_parameter |
| `CreateMaterialExpression()` | create_material_expression |
| `DeleteMaterialExpression()` | delete_material_expression |
| `ConnectMaterialExpressions()` | connect_material_expressions |
| `ConnectMaterialProperty()` | connect_material_expressions |
| `SetMaterialUsage()` | set_material_property |
| `RecompileMaterial()` | recompile_material |
| `LayoutMaterialExpressions()` | layout_material_graph |

## Testing

Same mock-based pattern as Tier 1:
- Mock `EditorBridge.run_command` with canned JSON responses
- Test each tool's output formatting and error paths
- Test helper upload still works with expanded module
- `_reset_state()` for test isolation

New test areas:
- Diagnostics warning thresholds
- Instance chain with multi-level hierarchy
- Compare output with added/removed/changed params
- Write operations return confirmation data
- Error cases: wrong param type, invalid expression class, connect to nonexistent pin

## Error Handling

Write operations add new error cases:
- "Cannot edit: asset is a MaterialInstanceConstant, not a Material" — for graph editing tools called on instances
- "Expression class not found: {class}" — invalid class name in create
- "Expression not found: {name}" — delete/connect referencing nonexistent expression
- "Parameter not found: {name}" — set_instance_parameter with wrong name
- "Recompile failed" — propagated from UE
