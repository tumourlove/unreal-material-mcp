# Missing Tier 1 & 2 Features — Design Document

**Date**: 2026-03-04
**Scope**: All missing features from Tier 1 (Inspection) and Tier 2 (Editing)

## Summary

3 existing tools extended + 10 new tools = complete Tier 1 & 2 coverage.

| Category | Change | Tool |
|----------|--------|------|
| Extend | Static switch branch detection | `get_material_parameters` |
| Extend | Texture sizes/formats | `get_material_dependencies` |
| Extend | Compile status/errors | `get_material_stats` |
| New T1 | Reverse lookup | `find_material_references` |
| New T1 | Breaking change detection | `find_breaking_changes` |
| New T1 | MF usage map & call chain | `find_material_function_usage` |
| New T1 | Find MIs by parent/dead/orphaned | `search_material_instances` |
| New T2 | Edit expression properties post-creation | `set_expression_property` |
| New T2 | Duplicate subgraph (same material) | `duplicate_expression_subgraph` |
| New T2 | Add/remove/rename parameters | `manage_material_parameter` |
| New T2 | Rename param across material + child MIs | `rename_parameter_cascade` |
| New T2 | Create MI from parent | `create_material_instance` |
| New T2 | Reparent MI | `reparent_material_instance` |
| New T2 | Bulk texture swap, param set, attribute set | `batch_update_materials` |

---

## Section 1: Extended Existing Tools

### 1.1 `get_material_parameters` — Static Switch Branch Detection

**What changes**: For each static switch parameter, add `value` (current default or instance override) and `controls` (which expressions this switch feeds into).

**UE APIs**:
- `MaterialEditingLibrary.get_material_default_static_switch_parameter_value(mat, name)` — base material default
- `MaterialEditingLibrary.get_material_instance_static_switch_parameter_value(inst, name)` — instance value
- Trace connections from StaticSwitchParameter expressions to find downstream If/StaticSwitch nodes

**Implementation in `material_helpers.py`**:
- In `get_all_parameters()`, after collecting static switch params, call the default value API
- For each StaticSwitchParameter expression, trace its output connections to identify which If-branch nodes it controls
- Add to parameter dict: `{"value": True/False, "controls": [{"expression": "If_0", "true_branch": "...", "false_branch": "..."}]}`

**Output change**: Static switch parameters go from:
```
  Roughness_Toggle (StaticSwitchParameter) default=None
```
to:
```
  Roughness_Toggle (StaticSwitchParameter) value=True
    Controls: MaterialExpressionIf_0 (true→Multiply_3, false→Constant_2)
```

### 1.2 `get_material_dependencies` — Texture Sizes & Formats

**What changes**: Each texture entry gains dimensions and pixel format.

**UE APIs**:
- `UTexture2D.blueprint_get_size_x()` / `blueprint_get_size_y()` — dimensions
- `UTexture2D.get_editor_property('pixel_format')` or `UTexture.source.get_size_x()` — pixel format via source data

**Implementation in `material_helpers.py`**:
- In `get_dependencies()`, when listing textures, load each texture asset
- Call `tex.blueprint_get_size_x()`, `tex.blueprint_get_size_y()`
- Read `tex.pixel_format` or `tex.get_editor_property('compression_settings')` for format info
- Add to texture dict: `{"width": 2048, "height": 2048, "format": "BC7"}`

**Output change**: Textures go from:
```
  /Game/Textures/T_Wood_BaseColor
```
to:
```
  /Game/Textures/T_Wood_BaseColor (2048x2048, BC7)
```

### 1.3 `get_material_stats` — Compile Status & Errors

**What changes**: Add `compile_status` and `compile_errors` fields.

**UE APIs**:
- `MaterialEditingLibrary.get_statistics(mat)` — already used, returns FMaterialStatistics
- For errors: attempt `mat.get_material_resource(platform).get_compile_errors()` via Python reflection
- Fallback: check if instruction count is 0 (indicates failed compilation)

**Implementation in `material_helpers.py`**:
- In `get_stats()`, after collecting instruction counts, determine compile status
- Try to access compile errors via Python bindings to `FMaterialResource.GetCompileErrors()`
- If Python API unavailable, infer from stats: if `num_pixel_shader_instructions == 0` and material has expressions, flag as `compile_failed`
- Add to result: `{"compile_status": "success|error|needs_recompile", "compile_errors": [...]}`

**Output change**: Stats section gains:
```
  Compile Status: ERROR
  Errors:
    - [SM5] Missing connection to BaseColor
    - [SM5] Invalid texture format for normal map
```

---

## Section 2: New Tier 1 Tools

### 2.1 `find_material_references` — Reverse Lookup

Find all assets that reference a given material or MI (meshes, actors, Niagara, UI, etc).

**Signature**:
```python
find_material_references(
    asset_path: str,           # Material/MI to find references for
    base_path: str = "/Game",  # Narrow search scope
    asset_types: str | None = None  # Optional comma-separated filter: "StaticMesh,SkeletalMesh"
)
```

**UE APIs**:
- `unreal.AssetRegistryHelpers.get_asset_registry()` → `get_referencers(package_name)`
- Filter results by `base_path` prefix and optional `asset_types`

**Implementation**:
1. Get asset registry via `unreal.AssetRegistryHelpers.get_asset_registry()`
2. Extract package name from asset_path
3. Call `registry.get_referencers(package_name)` to get dependent packages
4. For each referencer, get asset data to determine type and path
5. Filter by `base_path` and `asset_types`
6. Return with progress: `"Found N references (scanned M packages)"`

**Output**:
```
References to /Game/Materials/M_Character (12 found, 45 packages scanned):

  StaticMesh:
    /Game/Meshes/SM_CharacterBody
    /Game/Meshes/SM_CharacterHead

  SkeletalMesh:
    /Game/Characters/SK_MainCharacter

  Blueprint:
    /Game/Blueprints/BP_CharacterActor
```

### 2.2 `find_breaking_changes` — Breaking Change Detection

Preview what would break if a parameter or expression were removed.

**Signature**:
```python
find_breaking_changes(
    asset_path: str,                      # Material to check
    parameter_name: str | None = None,    # Parameter to check removal of
    expression_name: str | None = None,   # Expression to check removal of
    base_path: str = "/Game"              # Scope for MI search
)
```

**Implementation**:
1. **Parameter removal**: Find all child MIs (recursive via `GetChildInstances()`). Check which ones override the parameter. These would lose their override.
2. **Expression removal**: Trace downstream connections from the expression. List all expressions and output pins that would be disconnected.
3. Return structured report of impacts.

**Output**:
```
Breaking change analysis for removing parameter 'Roughness' from /Game/Materials/M_Character:

  Child instances with overrides (3):
    /Game/Materials/MI_Character_Pale (override: 0.3)
    /Game/Materials/MI_Character_Dark (override: 0.8)
    /Game/Materials/MI_Character_Wet (override: 0.1)

  Downstream connections (2):
    → MaterialExpressionMultiply_2 (input A)
    → MaterialExpressionLinearInterpolate_0 (input Alpha)
```

### 2.3 `find_material_function_usage` — MF Usage Map & Call Chain

Find which materials use a given MF, and trace nested MF dependencies.

**Signature**:
```python
find_material_function_usage(
    function_path: str,              # MaterialFunction asset path
    base_path: str = "/Game",        # Scope for material search
    include_chain: bool = False      # Include nested MF dependency tree
)
```

**Implementation**:
1. **Usage map**: Scan all materials under `base_path` via asset registry. For each, check `MaterialFunctionCall` expressions to see if they reference the target function.
2. **Call chain** (when `include_chain=True`): Load the function, find its `MaterialFunctionCall` expressions, recurse into each referenced function to build a dependency tree.

**Output**:
```
Usage of /Game/Functions/MF_NormalBlend (5 materials):

  /Game/Materials/M_Character → MaterialExpressionMaterialFunctionCall_0
  /Game/Materials/M_Weapon → MaterialExpressionMaterialFunctionCall_2
  /Game/Materials/M_Environment → MaterialExpressionMaterialFunctionCall_1
  /Game/Materials/M_Skin → MaterialExpressionMaterialFunctionCall_0
  /Game/Materials/M_Hair → MaterialExpressionMaterialFunctionCall_3

Call chain:
  MF_NormalBlend
    └── MF_PackNormal
    └── MF_UnpackNormal
        └── MF_TextureUtility
```

### 2.4 `search_material_instances` — Find MIs by Parent, Dead MIs, etc.

**Signature**:
```python
search_material_instances(
    base_path: str = "/Game",
    parent_path: str | None = None,  # Filter by parent material/MI
    filter_type: str = "all"         # "all", "by_parent", "dead", "orphaned"
)
```

**Implementation**:
1. Use asset registry to find all `MaterialInstanceConstant` assets under `base_path`
2. For each MI, load and inspect:
   - `"by_parent"`: Check if parent matches `parent_path`
   - `"dead"`: Count parameter overrides, flag if zero
   - `"orphaned"`: Check if parent asset exists / is loadable
3. Return with progress count.

**Output** (example: dead MIs):
```
Dead material instances under /Game (3 found, 47 MIs scanned):

  /Game/Materials/MI_Test_Old (parent: M_Character, 0 overrides)
  /Game/Materials/MI_Placeholder (parent: M_Default, 0 overrides)
  /Game/Materials/MI_Unused (parent: M_Environment, 0 overrides)
```

---

## Section 3: New Tier 2 Tools

### 3.1 `set_expression_property` — Edit Properties Post-Creation

**Signature**:
```python
set_expression_property(
    asset_path: str,         # Material asset path
    expression_name: str,    # Target expression (e.g. "MaterialExpressionMultiply_2")
    property_name: str,      # Property to set
    value: str               # New value (JSON-encoded for complex types)
)
```

**Supported properties by expression class**:
- **All parameters**: `parameter_name`, `group`, `sort_priority`, `desc`
- **ScalarParameter**: `default_value` (float)
- **VectorParameter**: `default_value` (JSON: `{"r":1,"g":0,"b":0,"a":1}`)
- **TextureSample/TextureSampleParameter2D**: `texture` (asset path)
- **Custom**: `code` (HLSL string), `output_type`
- **ComponentMask**: `r`, `g`, `b`, `a` (bool each)
- **TextureCoordinate**: `coordinate_index`, `u_tiling`, `v_tiling`
- **Constant**: `r` (float value)
- **Constant3Vector/Constant4Vector**: `constant` (JSON color)
- **Math ops (Add, Multiply, etc)**: `const_a`, `const_b` (float defaults)

**Implementation**: Load expression via `find_object()`, call `set_editor_property()` with type-appropriate conversion.

### 3.2 `duplicate_expression_subgraph` — Same Material Only

**Signature**:
```python
duplicate_expression_subgraph(
    asset_path: str,          # Material asset path
    root_expression: str,     # Expression to duplicate (with all upstream inputs)
    offset_x: int = 0,       # X offset for duplicated nodes
    offset_y: int = 300       # Y offset for duplicated nodes
)
```

**UE API**: `MaterialEditingLibrary.duplicate_material_expression(material, None, expression)` — duplicates a single expression with all properties.

**Implementation**:
1. Trace upstream from `root_expression` to collect all input expressions (reuse `_trace_expression` logic)
2. Build topological order (leaves first)
3. For each expression, call `DuplicateMaterialExpression()` to create a copy
4. Reconnect duplicated nodes to mirror original connections using `ConnectMaterialExpressions()`
5. Offset all duplicated node positions by `(offset_x, offset_y)`
6. Return mapping `{original_name: new_name}`

### 3.3 `manage_material_parameter` — Add/Remove/Rename Parameters

Parameters are expression nodes. This tool wraps create/delete/rename into a semantic operation.

**Signature**:
```python
manage_material_parameter(
    asset_path: str,
    action: str,                          # "add", "remove", "rename"
    parameter_name: str,                  # Target parameter name
    new_name: str | None = None,          # For "rename" action
    parameter_type: str | None = None,    # For "add": "scalar", "vector", "texture", "static_switch"
    default_value: str | None = None,     # For "add": default value
    group: str | None = None              # For "add": parameter group
)
```

**Implementation**:
- **add**: Map type to expression class (scalar→ScalarParameter, etc). Create expression via existing `create_expression()`. Set `parameter_name`, `default_value`, `group` via `set_editor_property()`.
- **remove**: Find expression by scanning for parameter with matching `parameter_name`. Delete via existing `delete_expression()`.
- **rename**: Find expression, call `set_editor_property('parameter_name', new_name)`.

### 3.4 `rename_parameter_cascade` — Rename Across Material + All Child MIs

**Signature**:
```python
rename_parameter_cascade(
    asset_path: str,         # Base material path
    old_name: str,           # Current parameter name
    new_name: str,           # New parameter name
    base_path: str = "/Game" # Scope for MI search
)
```

**Implementation**:
1. Find the parameter expression on the base material, rename it
2. Use `GetChildInstances()` recursively to collect all MIs
3. For each MI: check if it has an override for `old_name`. If so, read the value, clear the old override, set a new override with `new_name` and the same value.
4. Call `UpdateMaterialInstance()` on each modified MI
5. Return: `{"renamed_on_material": True, "instances_updated": N, "instances_scanned": M}`

**Safety**: This modifies potentially many assets. The tool returns a count of what will change.

### 3.5 `create_material_instance` — Create MI From Parent

**Signature**:
```python
create_material_instance(
    parent_path: str,                    # Parent material or MI
    instance_name: str,                  # Name for new MI (e.g. "MI_Character_Red")
    destination_path: str = ""           # Content path (default: same dir as parent)
)
```

**UE APIs**:
- `unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, path, MaterialInstanceConstant, factory)`
- `MaterialEditingLibrary.set_material_instance_parent(instance, parent)`

**Implementation**:
1. Create `MaterialInstanceConstantFactoryNew` factory
2. Create asset via `AssetTools.create_asset()`
3. Set parent via `SetMaterialInstanceParent()`
4. Mark package dirty (no auto-save)
5. Return new asset path

### 3.6 `reparent_material_instance` — Reparent MI

**Signature**:
```python
reparent_material_instance(
    instance_path: str,       # MI to reparent
    new_parent_path: str      # New parent material or MI
)
```

**UE API**: `MaterialEditingLibrary.set_material_instance_parent(instance, new_parent)` + `UpdateMaterialInstance()`

**Implementation**:
1. Load MI and new parent
2. Call `SetMaterialInstanceParent()`
3. Call `UpdateMaterialInstance()`
4. Return old parent path and new parent path

**Warning**: Reparenting may invalidate existing parameter overrides if the new parent doesn't have the same parameters. The tool should report which overrides would become orphaned.

### 3.7 `batch_update_materials` — Bulk Operations

**Signature**:
```python
batch_update_materials(
    base_path: str,                      # Search scope
    operation: str,                      # "swap_texture", "set_parameter", "set_attribute"
    filter_query: str = "",              # Filter materials (name match)
    filter_type: str = "name",           # "name", "parameter", "expression_type", "shading_model"
    # Operation-specific args (JSON string):
    operation_args: str = "{}"
)
```

**Operations**:
- **`swap_texture`**: `{"old_texture": "/Game/T_Old", "new_texture": "/Game/T_New"}` — scans all TextureSample expressions, replaces texture references
- **`set_parameter`**: `{"parameter_name": "Roughness", "value": "0.5", "parameter_type": "scalar"}` — sets parameter override on all matching MIs
- **`set_attribute`**: `{"property_name": "blend_mode", "value": "MASKED"}` — sets material property on matching base materials

**Implementation**:
1. Use `search_materials_in_path()` with filter to find target materials
2. For each target, apply the operation
3. Track and return: `{"processed": N, "modified": M, "errors": [...], "modified_assets": [...]}`

---

## UE API Summary

Key APIs used across all new features:

| API | Available in Python | Used For |
|-----|-------------------|----------|
| `AssetRegistryHelpers.get_asset_registry().get_referencers()` | Yes (BlueprintCallable) | Reverse lookup |
| `MaterialEditingLibrary.get_child_instances()` | Yes (BlueprintCallable) | Breaking changes, cascade rename |
| `MaterialEditingLibrary.get_material_default_static_switch_parameter_value()` | Yes (BlueprintPure) | Static switch values |
| `MaterialEditingLibrary.get_material_instance_static_switch_parameter_value()` | Yes (BlueprintPure) | Static switch values on MIs |
| `MaterialEditingLibrary.duplicate_material_expression()` | Yes (BlueprintCallable) | Subgraph duplication |
| `MaterialEditingLibrary.set_material_instance_parent()` | Yes (BlueprintCallable) | Create/reparent MI |
| `MaterialEditingLibrary.get_statistics()` | Yes (BlueprintCallable) | Extended stats |
| `UTexture2D.blueprint_get_size_x/y()` | Yes (BlueprintPure) | Texture dimensions |
| `AssetTools.create_asset()` | Yes | MI creation |
| `set_editor_property()` | Yes (Python reflection) | Expression property editing |

---

## Testing Strategy

Each new/extended feature gets:
1. **Unit test with mocked bridge** — verify output formatting and error handling
2. **Edge cases**: empty results, missing assets, circular references (MF call chains), large result sets

New test count estimate: ~25-30 new tests (2-3 per feature).

---

## Tool Count After Implementation

Current: 17 tools
New: +10 tools (find_material_references, find_breaking_changes, find_material_function_usage, search_material_instances, set_expression_property, duplicate_expression_subgraph, manage_material_parameter, rename_parameter_cascade, create_material_instance, reparent_material_instance, batch_update_materials)

Wait — that's 11 new tools. Let me recount:
1. find_material_references
2. find_breaking_changes
3. find_material_function_usage
4. search_material_instances
5. set_expression_property
6. duplicate_expression_subgraph
7. manage_material_parameter
8. rename_parameter_cascade
9. create_material_instance
10. reparent_material_instance
11. batch_update_materials

**Total after: 17 + 11 = 28 tools** (+ 3 existing tools extended)
