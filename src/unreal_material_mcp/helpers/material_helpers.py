"""Material helper functions that run inside the UE editor Python environment.

This module is uploaded to {UE_PROJECT_PATH}/Saved/MaterialMCP/ and executed
within Unreal Editor's embedded Python interpreter. It must NOT import anything
from our MCP package -- only ``unreal``, ``json``, and stdlib modules.

Every public function returns a JSON string.
"""

import json

try:
    import unreal
except ImportError:
    # Allow syntax checking / unit testing outside the editor.
    unreal = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Convenience aliases (resolved lazily so the module can be imported outside UE)
# ---------------------------------------------------------------------------

def _mel():
    """Return ``unreal.MaterialEditingLibrary`` (lazy)."""
    return unreal.MaterialEditingLibrary


def _eal():
    """Return ``unreal.EditorAssetLibrary`` (lazy)."""
    return unreal.EditorAssetLibrary


# ---------------------------------------------------------------------------
# Known expression class names (without the 'MaterialExpression' prefix).
# ---------------------------------------------------------------------------

KNOWN_EXPRESSION_CLASSES = [
    # Math
    "Add", "Subtract", "Multiply", "Divide", "Clamp", "OneMinus", "Power",
    "Abs", "Floor", "Ceil", "Frac", "Fmod", "Min", "Max", "Dot", "CrossProduct",
    "Saturate", "Round", "Truncate", "Sign", "SquareRoot", "Length",
    "Cosine", "Sine", "Tangent", "Arcsine", "Arccosine", "Arctangent",
    "Arctangent2", "Exponential", "Exponential2", "Logarithm",
    "InverseLinearInterpolate", "Step", "SmoothStep",
    # Vector ops
    "ComponentMask", "AppendVector", "Normalize", "TransformPosition",
    "TransformVector", "BreakMaterialAttributes", "MakeMaterialAttributes",
    "GetMaterialAttributes", "BlendMaterialAttributes", "DeriveNormalZ",
    "CrossProduct", "DotProduct",
    # Parameters
    "ScalarParameter", "VectorParameter", "TextureSampleParameter2D",
    "TextureSampleParameter2DArray", "TextureObjectParameter",
    "StaticSwitchParameter", "StaticBoolParameter",
    "ChannelMaskParameterColor", "CollectionParameter",
    # Constants
    "Constant", "Constant2Vector", "Constant3Vector", "Constant4Vector",
    "StaticBool", "ConstantBiasScale",
    # Texture
    "TextureSample", "TextureCoordinate", "TextureObject",
    # Utility / misc
    "LinearInterpolate", "If", "IfThenElse", "Custom", "MaterialFunctionCall",
    "Comment", "Reroute", "NamedRerouteDeclaration", "NamedRerouteUsage",
    "VertexColor", "Time", "Fresnel", "DepthFade", "WorldPosition",
    "PixelDepth", "SceneDepth", "ScreenPosition",
    "DepthOfFieldFunction", "SphereMask", "Distance", "DistanceCullFade",
    "CameraPositionWS", "ActorPositionWS", "ObjectRadius",
    "Panner", "Rotator", "Desaturation",
    "CameraVectorWS", "PixelNormalWS", "VertexNormalWS",
    "TwoSidedSign", "ObjectPositionWS",
    "BumpOffset", "BlackBody", "HsvToRgb",
    "FunctionInput", "FunctionOutput",
    "FeatureLevelSwitch", "QualitySwitch", "ShadingPathSwitch",
    "DynamicParameter", "ParticleColor", "ParticlePositionWS",
    "CustomOutput", "VertexInterpolator",
    "DDX", "DDY", "Noise",
    "GIReplace", "LightmassReplace",
    "SceneColor", "SceneTexture",
    "DecalDerivative", "DecalMipmapLevel",
    "PerInstanceRandom", "PerInstanceFadeAmount", "PerInstanceCustomData",
]

# Material output properties we can trace from.
_MATERIAL_PROPERTIES = [
    ("BaseColor", "MP_BASE_COLOR"),
    ("Metallic", "MP_METALLIC"),
    ("Specular", "MP_SPECULAR"),
    ("Roughness", "MP_ROUGHNESS"),
    ("Anisotropy", "MP_ANISOTROPY"),
    ("EmissiveColor", "MP_EMISSIVE_COLOR"),
    ("Opacity", "MP_OPACITY"),
    ("OpacityMask", "MP_OPACITY_MASK"),
    ("Normal", "MP_NORMAL"),
    ("WorldPositionOffset", "MP_WORLD_POSITION_OFFSET"),
    ("SubsurfaceColor", "MP_SUBSURFACE_COLOR"),
    ("AmbientOcclusion", "MP_AMBIENT_OCCLUSION"),
    ("Refraction", "MP_REFRACTION"),
    ("PixelDepthOffset", "MP_PIXEL_DEPTH_OFFSET"),
    ("ShadingModel", "MP_SHADING_MODEL"),
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_enum_name(value):
    """Return the display name of a UE enum value, or str(value) as fallback.

    UE Python enums str() as '<BlendMode.BLEND_MASKED: 1>' — we extract 'BLEND_MASKED'.
    """
    try:
        name = str(value)
        # Strip angle brackets: '<BlendMode.BLEND_MASKED: 1>' -> 'BlendMode.BLEND_MASKED: 1'
        if name.startswith("<") and name.endswith(">"):
            name = name[1:-1]
        # Strip the value suffix: 'BlendMode.BLEND_MASKED: 1' -> 'BlendMode.BLEND_MASKED'
        if ": " in name:
            name = name.rsplit(": ", 1)[0]
        # Strip the enum class prefix: 'BlendMode.BLEND_MASKED' -> 'BLEND_MASKED'
        if "." in name:
            name = name.rsplit(".", 1)[-1]
        return name
    except Exception:
        return str(value)


def _asset_parts(asset_path):
    """Split ``/Game/Materials/M_Foo`` into (package, asset_name)."""
    parts = asset_path.rsplit("/", 1)
    pkg = parts[0] if len(parts) == 2 else ""
    asset_name = parts[-1]
    # Strip trailing .AssetName if present
    if "." in asset_name:
        asset_name = asset_name.split(".")[0]
    return pkg, asset_name


def _full_object_path(asset_path):
    """Return the full package path used by find_object, e.g. '/Game/Materials/M_Foo.M_Foo'."""
    _, asset_name = _asset_parts(asset_path)
    path = asset_path
    if "." not in path:
        path = f"{path}.{asset_name}"
    return path


def _expr_position(expr):
    """Return (x, y) editor position for an expression node."""
    try:
        x = expr.get_editor_property("material_expression_editor_x")
        y = expr.get_editor_property("material_expression_editor_y")
        return {"x": int(x), "y": int(y)}
    except Exception:
        return {"x": 0, "y": 0}


def _expr_id(expr):
    """Return a short human-readable identifier for an expression."""
    if expr is None:
        return None
    try:
        name = expr.get_name()
    except Exception:
        name = str(expr)
    return name


def _load_material(asset_path):
    """Load and return a material or material instance asset, or raise."""
    mat = _eal().load_asset(asset_path)
    if mat is None:
        raise ValueError(f"Asset not found: {asset_path}")
    return mat


def _is_material_instance(mat):
    """Return True if *mat* is a MaterialInstanceConstant."""
    return isinstance(mat, unreal.MaterialInstanceConstant)


def _error_json(message):
    """Return a JSON error envelope."""
    return json.dumps({"success": False, "error": str(message)})


# ---------------------------------------------------------------------------
# 1. get_material_info
# ---------------------------------------------------------------------------

def get_material_info(asset_path):
    """Return JSON with core material metadata.

    For base materials: blend_mode, shading_model, material_domain, two_sided,
    expression_count, usage_flags.
    For MaterialInstanceConstant: additionally returns parent path.
    """
    try:
        mat = _load_material(asset_path)

        info = {"asset_path": asset_path, "success": True}

        if _is_material_instance(mat):
            info["asset_type"] = "MaterialInstanceConstant"
            try:
                parent = mat.get_editor_property("parent")
                info["parent"] = parent.get_path_name() if parent else None
            except Exception:
                info["parent"] = None
            # MICs inherit most properties from parent; expose what we can.
            try:
                info["two_sided"] = bool(mat.get_editor_property("override_subsurface_profile"))
            except Exception:
                pass
        else:
            info["asset_type"] = "Material"
            try:
                info["blend_mode"] = _safe_enum_name(mat.get_editor_property("blend_mode"))
            except Exception:
                info["blend_mode"] = "Unknown"
            try:
                info["shading_model"] = _safe_enum_name(mat.get_editor_property("shading_model"))
            except Exception:
                info["shading_model"] = "Unknown"
            try:
                info["material_domain"] = _safe_enum_name(mat.get_editor_property("material_domain"))
            except Exception:
                info["material_domain"] = "Unknown"
            try:
                info["two_sided"] = bool(mat.get_editor_property("two_sided"))
            except Exception:
                info["two_sided"] = False
            try:
                info["expression_count"] = int(_mel().get_num_material_expressions(mat))
            except Exception:
                info["expression_count"] = -1

            # Usage flags
            usage_flags = {}
            usage_props = [
                "usage_automatically_set_at_editor_time",
                "usage_decals",
                "usage_skeletal_mesh",
                "usage_particle_sprites",
                "usage_beam_trails",
                "usage_mesh_particles",
                "usage_static_lighting",
                "usage_morph_targets",
                "usage_clothing",
                "usage_nanite",
            ]
            for prop in usage_props:
                try:
                    usage_flags[prop.replace("usage_", "")] = bool(
                        mat.get_editor_property(prop)
                    )
                except Exception:
                    pass
            if usage_flags:
                info["usage_flags"] = usage_flags

        return json.dumps(info)
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# 2. get_all_parameters
# ---------------------------------------------------------------------------

def get_all_parameters(asset_path):
    """Return JSON listing every parameter name, type, and default value."""
    try:
        mat = _load_material(asset_path)
        mel = _mel()

        params = []

        # Scalar
        try:
            for name in mel.get_scalar_parameter_names(mat):
                name_str = str(name)
                try:
                    default = float(
                        mel.get_material_default_scalar_parameter_value(mat, name_str)
                    )
                except Exception:
                    default = None
                params.append({
                    "name": name_str,
                    "type": "Scalar",
                    "default": default,
                })
        except Exception:
            pass

        # Vector
        try:
            for name in mel.get_vector_parameter_names(mat):
                name_str = str(name)
                try:
                    v = mel.get_material_default_vector_parameter_value(mat, name_str)
                    default = {"r": v.r, "g": v.g, "b": v.b, "a": v.a}
                except Exception:
                    default = None
                params.append({
                    "name": name_str,
                    "type": "Vector",
                    "default": default,
                })
        except Exception:
            pass

        # Texture
        try:
            for name in mel.get_texture_parameter_names(mat):
                name_str = str(name)
                try:
                    tex = mel.get_material_default_texture_parameter_value(mat, name_str)
                    default = tex.get_path_name() if tex else None
                except Exception:
                    default = None
                params.append({
                    "name": name_str,
                    "type": "Texture",
                    "default": default,
                })
        except Exception:
            pass

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

                # Trace controls: find StaticSwitchParameter expressions
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

        return json.dumps({"success": True, "asset_path": asset_path, "parameters": params})
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# 3. scan_all_expressions
# ---------------------------------------------------------------------------

def _extract_expression_props(expr, class_name):
    """Extract notable properties from an expression based on its class."""
    props = {}
    props["position"] = _expr_position(expr)

    # Parameter name (shared by all parameter expression types)
    if "Parameter" in class_name:
        try:
            props["parameter_name"] = str(expr.get_editor_property("parameter_name"))
        except Exception:
            pass

    # Description / comment
    try:
        desc = expr.get_editor_property("desc")
        if desc:
            props["desc"] = str(desc)
    except Exception:
        pass

    # Class-specific properties
    if class_name == "ComponentMask":
        for ch in ("r", "g", "b", "a"):
            try:
                props[ch] = bool(expr.get_editor_property(ch))
            except Exception:
                pass

    elif class_name == "Custom":
        try:
            props["code"] = str(expr.get_editor_property("code"))
        except Exception:
            pass
        try:
            props["output_type"] = _safe_enum_name(expr.get_editor_property("output_type"))
        except Exception:
            pass

    elif class_name in ("Constant",):
        try:
            props["value"] = float(expr.get_editor_property("r"))
        except Exception:
            pass

    elif class_name == "Constant2Vector":
        try:
            props["r"] = float(expr.get_editor_property("r"))
            props["g"] = float(expr.get_editor_property("g"))
        except Exception:
            pass

    elif class_name == "Constant3Vector":
        try:
            c = expr.get_editor_property("constant")
            props["value"] = {"r": c.r, "g": c.g, "b": c.b}
        except Exception:
            pass

    elif class_name == "Constant4Vector":
        try:
            c = expr.get_editor_property("constant")
            props["value"] = {"r": c.r, "g": c.g, "b": c.b, "a": c.a}
        except Exception:
            pass

    elif class_name == "TextureCoordinate":
        try:
            props["coordinate_index"] = int(expr.get_editor_property("coordinate_index"))
        except Exception:
            pass
        try:
            props["u_tiling"] = float(expr.get_editor_property("u_tiling"))
            props["v_tiling"] = float(expr.get_editor_property("v_tiling"))
        except Exception:
            pass

    elif class_name in ("TextureSample", "TextureSampleParameter2D",
                        "TextureSampleParameter2DArray", "TextureObjectParameter"):
        try:
            tex = expr.get_editor_property("texture")
            props["texture"] = tex.get_path_name() if tex else None
        except Exception:
            pass

    elif class_name == "MaterialFunctionCall":
        try:
            fn = expr.get_editor_property("material_function")
            props["function"] = fn.get_path_name() if fn else None
        except Exception:
            pass

    elif class_name == "Comment":
        try:
            props["text"] = str(expr.get_editor_property("text"))
        except Exception:
            pass
        try:
            props["size_x"] = int(expr.get_editor_property("size_x"))
            props["size_y"] = int(expr.get_editor_property("size_y"))
        except Exception:
            pass

    elif class_name == "StaticBool":
        try:
            props["value"] = bool(expr.get_editor_property("value"))
        except Exception:
            pass

    elif class_name == "If":
        try:
            props["a_greater_than_b"] = float(expr.get_editor_property("a_greater_than_b"))
        except Exception:
            pass

    elif class_name == "Panner":
        try:
            props["speed_x"] = float(expr.get_editor_property("speed_x"))
            props["speed_y"] = float(expr.get_editor_property("speed_y"))
        except Exception:
            pass

    elif class_name == "Rotator":
        try:
            props["center_x"] = float(expr.get_editor_property("center_x"))
            props["center_y"] = float(expr.get_editor_property("center_y"))
            props["speed"] = float(expr.get_editor_property("speed"))
        except Exception:
            pass

    return props


def scan_all_expressions(asset_path, class_filter=None):
    """Brute-force scan material expressions via ``unreal.find_object``.

    Parameters
    ----------
    asset_path : str
        The material asset path (e.g. ``/Game/Materials/M_Foo``).
    class_filter : str or None
        If provided, only scan this expression class name (e.g. ``"Add"``).
        Otherwise scan all known classes.

    Returns
    -------
    str
        JSON with ``success``, ``expression_count``, and ``expressions`` list.
    """
    try:
        mat = _load_material(asset_path)
        mel = _mel()

        full_path = _full_object_path(asset_path)

        try:
            target_count = int(mel.get_num_material_expressions(mat))
        except Exception:
            target_count = -1

        classes_to_scan = (
            [class_filter] if class_filter else KNOWN_EXPRESSION_CLASSES
        )

        found = []
        found_count = 0
        # Max index per class. Expression indices can have large gaps (deleted
        # nodes leave holes) so we scan broadly.  200 is generous but keeps
        # total find_object calls manageable (~100 classes * 200 = 20k).
        MAX_INDEX = 200

        for cls_name in classes_to_scan:
            consecutive_misses = 0
            for i in range(MAX_INDEX):
                obj_path = f"{full_path}:MaterialExpression{cls_name}_{i}"
                expr = unreal.find_object(None, obj_path)
                if expr is None:
                    consecutive_misses += 1
                    # After 30 consecutive misses, assume this class is done.
                    # High enough to survive typical gaps from deleted nodes.
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
                found.append(entry)

                # Early termination: found all expressions
                if 0 < target_count <= found_count:
                    break

            if 0 < target_count <= found_count:
                break

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "expected_expression_count": target_count,
            "found_expression_count": found_count,
            "expressions": found,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# 4. trace_connections
# ---------------------------------------------------------------------------

def _trace_expression(mat, expr, mel, visited=None, depth=0, max_depth=50):
    """Recursively trace inputs of a single expression node."""
    if expr is None:
        return None
    if visited is None:
        visited = set()
    if depth > max_depth:
        return {"name": _expr_id(expr), "truncated": True}

    expr_name = _expr_id(expr)
    if expr_name in visited:
        return {"name": expr_name, "cycle": True}
    visited.add(expr_name)

    node = {
        "name": expr_name,
        "position": _expr_position(expr),
    }

    # Get input names
    try:
        input_names = mel.get_material_expression_input_names(expr)
        input_names = [str(n) for n in input_names]
    except Exception:
        input_names = []

    # Get connected inputs
    try:
        connected = mel.get_inputs_for_material_expression(mat, expr)
    except Exception:
        connected = []

    inputs = []
    for idx, connected_expr in enumerate(connected):
        if connected_expr is None:
            continue
        in_name = input_names[idx] if idx < len(input_names) else f"Input_{idx}"
        child = _trace_expression(mat, connected_expr, mel, visited, depth + 1, max_depth)
        if child is not None:
            inputs.append({"input_name": in_name, "connected_node": child})

    if inputs:
        node["inputs"] = inputs

    return node


def trace_connections(asset_path, expression_name=None):
    """Trace material node connections and return a JSON tree.

    Parameters
    ----------
    asset_path : str
        Material asset path.
    expression_name : str or None
        If provided, find this expression via ``find_object`` and trace its
        input tree.  The name should be the full object sub-path suffix, e.g.
        ``"MaterialExpressionAdd_0"``.
        If omitted, trace from every connected material output pin.

    Returns
    -------
    str
        JSON with ``success`` and ``tree`` (or ``trees`` for output pins).
    """
    try:
        mat = _load_material(asset_path)
        mel = _mel()
        full_path = _full_object_path(asset_path)

        if expression_name is not None:
            # Ensure the name has the prefix
            if not expression_name.startswith("MaterialExpression"):
                expression_name = f"MaterialExpression{expression_name}"
            obj_path = f"{full_path}:{expression_name}"
            expr = unreal.find_object(None, obj_path)
            if expr is None:
                return _error_json(f"Expression not found: {obj_path}")
            tree = _trace_expression(mat, expr, mel)
            return json.dumps({"success": True, "asset_path": asset_path, "tree": tree})

        # Trace from all material output pins
        trees = {}
        for prop_label, prop_attr in _MATERIAL_PROPERTIES:
            try:
                prop_enum = getattr(unreal.MaterialProperty, prop_attr)
                node = mel.get_material_property_input_node(mat, prop_enum)
                if node is not None:
                    tree = _trace_expression(mat, node, mel)
                    if tree is not None:
                        trees[prop_label] = tree
            except Exception:
                continue

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "output_pins": trees,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# 5. search_materials_in_path
# ---------------------------------------------------------------------------

def search_materials_in_path(base_path, query="", filter_type="name"):
    """Search for materials / material instances under *base_path*.

    Parameters
    ----------
    base_path : str
        Content-browser path (e.g. ``/Game/Materials``).
    query : str
        Search string.  Interpretation depends on *filter_type*.
    filter_type : str
        One of:
        - ``"name"`` — substring match on asset name (default).
        - ``"parameter"`` — match materials containing a parameter whose name
          includes *query*.
        - ``"expression"`` — match materials containing an expression class
          whose name includes *query*.
        - ``"shading_model"`` — match materials whose shading model name
          includes *query*.

    Returns
    -------
    str
        JSON with ``success`` and ``results`` list.
    """
    try:
        ar = unreal.AssetRegistryHelpers.get_asset_registry()
        all_assets = ar.get_assets_by_path(base_path, recursive=True)

        material_class_names = {"Material", "MaterialInstanceConstant"}
        results = []
        query_lower = query.lower()

        for asset_data in all_assets:
            try:
                class_name = str(asset_data.asset_class_path.asset_name)
            except Exception:
                try:
                    class_name = str(asset_data.asset_class)
                except Exception:
                    continue

            if class_name not in material_class_names:
                continue

            asset_path = str(asset_data.package_name)
            asset_name = str(asset_data.asset_name)

            # Quick name filter (always applied cheaply)
            if filter_type == "name":
                if query_lower and query_lower not in asset_name.lower():
                    continue
                results.append({
                    "asset_path": asset_path,
                    "asset_name": asset_name,
                    "class": class_name,
                })
                continue

            # For deeper filters we need to load the asset
            try:
                mat = _eal().load_asset(asset_path)
                if mat is None:
                    continue
            except Exception:
                continue

            if filter_type == "parameter":
                mel = _mel()
                matched = False
                for getter in (
                    mel.get_scalar_parameter_names,
                    mel.get_vector_parameter_names,
                    mel.get_texture_parameter_names,
                    mel.get_static_switch_parameter_names,
                ):
                    try:
                        names = getter(mat)
                        for n in names:
                            if query_lower in str(n).lower():
                                matched = True
                                break
                    except Exception:
                        pass
                    if matched:
                        break
                if not matched:
                    continue
                results.append({
                    "asset_path": asset_path,
                    "asset_name": asset_name,
                    "class": class_name,
                })

            elif filter_type == "expression":
                if class_name == "MaterialInstanceConstant":
                    # Instances don't own expressions
                    continue
                fp = _full_object_path(asset_path)
                matched = False
                for cls in KNOWN_EXPRESSION_CLASSES:
                    if query_lower and query_lower not in cls.lower():
                        continue
                    obj_path = f"{fp}:MaterialExpression{cls}_0"
                    if unreal.find_object(None, obj_path) is not None:
                        matched = True
                        break
                if not matched:
                    continue
                results.append({
                    "asset_path": asset_path,
                    "asset_name": asset_name,
                    "class": class_name,
                })

            elif filter_type == "shading_model":
                if class_name != "Material":
                    continue
                try:
                    sm = _safe_enum_name(mat.get_editor_property("shading_model"))
                except Exception:
                    continue
                if query_lower and query_lower not in sm.lower():
                    continue
                results.append({
                    "asset_path": asset_path,
                    "asset_name": asset_name,
                    "class": class_name,
                    "shading_model": sm,
                })
            else:
                # Unknown filter_type — fall back to name match
                if query_lower and query_lower not in asset_name.lower():
                    continue
                results.append({
                    "asset_path": asset_path,
                    "asset_name": asset_name,
                    "class": class_name,
                })

        return json.dumps({
            "success": True,
            "base_path": base_path,
            "filter_type": filter_type,
            "query": query,
            "count": len(results),
            "results": results,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# 6. get_stats
# ---------------------------------------------------------------------------

def get_stats(asset_path):
    """Return material statistics, warnings, and disconnected-expression analysis.

    Only works on base Materials (not MaterialInstanceConstant).

    Returns
    -------
    str
        JSON with ``success``, ``stats``, ``warnings``, and disconnected info.
    """
    try:
        mat = _load_material(asset_path)

        if _is_material_instance(mat):
            return _error_json(
                "get_stats is not supported on MaterialInstanceConstant. "
                "Use the parent Material instead."
            )

        mel = _mel()
        warnings = []

        # --- Shader statistics ---
        stats = {}
        try:
            s = mel.get_statistics(mat)
            stats = {
                "num_vertex_shader_instructions": int(s.num_vertex_shader_instructions),
                "num_pixel_shader_instructions": int(s.num_pixel_shader_instructions),
                "num_samplers": int(s.num_samplers),
                "num_vertex_texture_samples": int(s.num_vertex_texture_samples),
                "num_pixel_texture_samples": int(s.num_pixel_texture_samples),
                "num_virtual_texture_samples": int(s.num_virtual_texture_samples),
                "num_uv_scalars": int(s.num_uv_scalars),
                "num_interpolator_scalars": int(s.num_interpolator_scalars),
            }
            if stats["num_samplers"] > 16:
                warnings.append(
                    f"Sampler count ({stats['num_samplers']}) exceeds limit of 16"
                )
            if stats["num_pixel_shader_instructions"] > 500:
                warnings.append(
                    f"Pixel shader instructions ({stats['num_pixel_shader_instructions']}) "
                    "exceeds recommended maximum of 500"
                )
        except Exception as exc:
            stats["error"] = str(exc)

        # --- Disconnected expression analysis ---
        # Get all expressions (excluding comments)
        all_exprs_data = json.loads(scan_all_expressions(asset_path))
        all_expr_names = set()
        param_expr_names = set()
        if all_exprs_data.get("success"):
            for expr in all_exprs_data.get("expressions", []):
                if expr.get("class") == "Comment":
                    continue
                name = expr.get("name")
                if name:
                    all_expr_names.add(name)
                if "Parameter" in expr.get("class", ""):
                    if name:
                        param_expr_names.add(name)

        # Get connected expressions by tracing from output pins
        trace_data = json.loads(trace_connections(asset_path))
        connected_names = set()
        if trace_data.get("success"):
            def _collect_names(node):
                if node is None:
                    return
                n = node.get("name")
                if n:
                    connected_names.add(n)
                for inp in node.get("inputs", []):
                    _collect_names(inp.get("connected_node"))

            # Trace from output pins
            for _pin, tree in trace_data.get("output_pins", {}).items():
                _collect_names(tree)
            # Also handle single-tree mode
            if "tree" in trace_data:
                _collect_names(trace_data["tree"])

        disconnected = sorted(all_expr_names - connected_names)
        unused_params = sorted(param_expr_names - connected_names)

        if unused_params:
            warnings.append(
                f"Unused parameter expressions: {', '.join(unused_params)}"
            )

        # --- Compile status ---
        compile_status = "success"
        compile_errors = []
        try:
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
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# 7. get_dependencies
# ---------------------------------------------------------------------------

def get_dependencies(asset_path):
    """Return textures, material functions, and parameter sources for a material.

    Returns
    -------
    str
        JSON with ``textures``, ``material_functions``, and ``parameter_sources``.
    """
    try:
        mat = _load_material(asset_path)
        mel = _mel()

        # --- Textures ---
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

        # --- Material functions ---
        material_functions = []
        try:
            fn_data = json.loads(
                scan_all_expressions(asset_path, class_filter="MaterialFunctionCall")
            )
            if fn_data.get("success"):
                for expr in fn_data.get("expressions", []):
                    fn_path = expr.get("function")
                    if fn_path and fn_path not in material_functions:
                        material_functions.append(fn_path)
        except Exception:
            pass

        # --- Parameter sources ---
        parameter_sources = []
        param_type_getters = {
            "Scalar": "get_scalar_parameter_source",
            "Vector": "get_vector_parameter_source",
            "Texture": "get_texture_parameter_source",
            "StaticSwitch": "get_static_switch_parameter_source",
        }
        param_name_getters = {
            "Scalar": "get_scalar_parameter_names",
            "Vector": "get_vector_parameter_names",
            "Texture": "get_texture_parameter_names",
            "StaticSwitch": "get_static_switch_parameter_names",
        }
        for ptype, source_getter_name in param_type_getters.items():
            try:
                names = getattr(mel, param_name_getters[ptype])(mat)
                source_fn = getattr(mel, source_getter_name)
                for name in names:
                    name_str = str(name)
                    try:
                        found, source_path = source_fn(mat, name_str)
                        parameter_sources.append({
                            "name": name_str,
                            "type": ptype,
                            "found": bool(found),
                            "source": str(source_path) if found else None,
                        })
                    except Exception:
                        parameter_sources.append({
                            "name": name_str,
                            "type": ptype,
                            "found": False,
                            "source": None,
                        })
            except Exception:
                pass

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "textures": textures,
            "material_functions": material_functions,
            "parameter_sources": parameter_sources,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# 8. inspect_function
# ---------------------------------------------------------------------------

def inspect_function(asset_path, function_name=None):
    """Inspect a MaterialFunction asset or a MaterialFunctionCall in a material.

    Parameters
    ----------
    asset_path : str
        If *function_name* is given, this is the material containing the
        function call.  Otherwise, this is the function asset path itself.
    function_name : str or None
        Name of a MaterialFunctionCall expression in the material (e.g.
        ``"MaterialExpressionMaterialFunctionCall_0"``).

    Returns
    -------
    str
        JSON with function metadata, expressions, inputs, and outputs.
    """
    try:
        mel = _mel()

        if function_name is not None:
            # Mode 1: asset_path is a material, function_name is an expression
            mat = _load_material(asset_path)
            full_path = _full_object_path(asset_path)

            if not function_name.startswith("MaterialExpression"):
                function_name = f"MaterialExpression{function_name}"
            obj_path = f"{full_path}:{function_name}"
            expr = unreal.find_object(None, obj_path)
            if expr is None:
                return _error_json(f"Expression not found: {obj_path}")

            try:
                fn = expr.get_editor_property("material_function")
            except Exception:
                return _error_json(
                    f"Could not get material_function from {function_name}"
                )
            if fn is None:
                return _error_json(f"No material function set on {function_name}")
            fn_path = fn.get_path_name()
        else:
            # Mode 2: asset_path IS the function
            fn = _eal().load_asset(asset_path)
            if fn is None:
                return _error_json(f"Function asset not found: {asset_path}")
            fn_path = asset_path

        # --- Function metadata ---
        info = {
            "function_path": fn_path,
        }
        try:
            info["description"] = str(fn.get_editor_property("description"))
        except Exception:
            info["description"] = ""
        try:
            info["user_exposed_caption"] = str(
                fn.get_editor_property("user_exposed_caption")
            )
        except Exception:
            info["user_exposed_caption"] = ""

        # Expression count
        try:
            info["expression_count"] = int(
                mel.get_num_material_expressions_in_function(fn)
            )
        except Exception:
            info["expression_count"] = -1

        # --- Brute-force scan expressions inside the function ---
        fn_full_path = _full_object_path(fn_path)
        MAX_INDEX = 200
        found = []
        inputs_list = []
        outputs_list = []

        for cls_name in KNOWN_EXPRESSION_CLASSES:
            consecutive_misses = 0
            for i in range(MAX_INDEX):
                obj_path = f"{fn_full_path}:MaterialExpression{cls_name}_{i}"
                expr_obj = unreal.find_object(None, obj_path)
                if expr_obj is None:
                    consecutive_misses += 1
                    if consecutive_misses >= 30:
                        break
                    continue

                consecutive_misses = 0
                entry = {
                    "class": cls_name,
                    "index": i,
                    "name": _expr_id(expr_obj),
                }
                entry.update(_extract_expression_props(expr_obj, cls_name))
                found.append(entry)

                # Collect inputs/outputs for convenience
                if cls_name == "FunctionInput":
                    inp = {"name": _expr_id(expr_obj), "index": i}
                    try:
                        inp["input_name"] = str(
                            expr_obj.get_editor_property("input_name")
                        )
                    except Exception:
                        pass
                    try:
                        inp["input_type"] = _safe_enum_name(
                            expr_obj.get_editor_property("input_type")
                        )
                    except Exception:
                        pass
                    inputs_list.append(inp)
                elif cls_name == "FunctionOutput":
                    out = {"name": _expr_id(expr_obj), "index": i}
                    try:
                        out["output_name"] = str(
                            expr_obj.get_editor_property("output_name")
                        )
                    except Exception:
                        pass
                    outputs_list.append(out)

        info["found_expression_count"] = len(found)
        info["expressions"] = found
        info["inputs"] = inputs_list
        info["outputs"] = outputs_list

        return json.dumps({"success": True, "asset_path": asset_path, **info})
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# 9. get_instance_chain
# ---------------------------------------------------------------------------

def get_instance_chain(asset_path):
    """Walk the parent chain of a material instance and list children.

    Returns overridden parameters at each MI level and root material properties.

    Returns
    -------
    str
        JSON with ``chain`` (list of ancestors) and ``children``.
    """
    try:
        mat = _load_material(asset_path)
        mel = _mel()

        chain = []
        visited = set()
        current = mat
        current_path = asset_path

        while current is not None:
            if current_path in visited:
                chain.append({
                    "asset_path": current_path,
                    "cycle_detected": True,
                })
                break
            visited.add(current_path)

            if _is_material_instance(current):
                # Collect overridden parameters
                overrides = []
                # Scalar
                try:
                    for name in mel.get_scalar_parameter_names(current):
                        name_str = str(name)
                        try:
                            val = float(
                                mel.get_material_instance_scalar_parameter_value(
                                    current, name_str
                                )
                            )
                            overrides.append({
                                "name": name_str,
                                "type": "Scalar",
                                "value": val,
                            })
                        except Exception:
                            pass
                except Exception:
                    pass
                # Vector
                try:
                    for name in mel.get_vector_parameter_names(current):
                        name_str = str(name)
                        try:
                            v = mel.get_material_instance_vector_parameter_value(
                                current, name_str
                            )
                            overrides.append({
                                "name": name_str,
                                "type": "Vector",
                                "value": {"r": v.r, "g": v.g, "b": v.b, "a": v.a},
                            })
                        except Exception:
                            pass
                except Exception:
                    pass
                # Texture
                try:
                    for name in mel.get_texture_parameter_names(current):
                        name_str = str(name)
                        try:
                            tex = mel.get_material_instance_texture_parameter_value(
                                current, name_str
                            )
                            overrides.append({
                                "name": name_str,
                                "type": "Texture",
                                "value": tex.get_path_name() if tex else None,
                            })
                        except Exception:
                            pass
                except Exception:
                    pass
                # Static switch
                try:
                    for name in mel.get_static_switch_parameter_names(current):
                        name_str = str(name)
                        try:
                            val = bool(
                                mel.get_material_instance_static_switch_parameter_value(
                                    current, name_str
                                )
                            )
                            overrides.append({
                                "name": name_str,
                                "type": "StaticSwitch",
                                "value": val,
                            })
                        except Exception:
                            pass
                except Exception:
                    pass

                entry = {
                    "asset_path": current_path,
                    "asset_type": "MaterialInstanceConstant",
                    "overrides": overrides,
                }
                chain.append(entry)

                # Walk to parent
                try:
                    parent = current.get_editor_property("parent")
                    if parent is not None:
                        current_path = parent.get_path_name()
                        current = parent
                    else:
                        current = None
                except Exception:
                    current = None
            else:
                # Root Material
                entry = {
                    "asset_path": current_path,
                    "asset_type": "Material",
                }
                try:
                    entry["blend_mode"] = _safe_enum_name(
                        current.get_editor_property("blend_mode")
                    )
                except Exception:
                    pass
                try:
                    entry["shading_model"] = _safe_enum_name(
                        current.get_editor_property("shading_model")
                    )
                except Exception:
                    pass
                chain.append(entry)
                current = None  # Root reached

        # --- Children ---
        children = []
        try:
            child_instances = mel.get_child_instances(mat)
            for child in child_instances:
                try:
                    children.append({
                        "package_name": str(child.package_name),
                        "asset_name": str(child.asset_name),
                    })
                except Exception:
                    children.append(str(child))
        except Exception:
            pass

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "chain": chain,
            "children": children,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# 10. compare_materials
# ---------------------------------------------------------------------------

def compare_materials(path_a, path_b):
    """Compare two materials side-by-side.

    Diffs parameters, and for base materials also compares properties, stats,
    and expression counts by class.

    Returns
    -------
    str
        JSON with ``parameter_diff``, ``property_diff``, ``stats_diff``,
        and ``expression_diff``.
    """
    try:
        mat_a = _load_material(path_a)
        mat_b = _load_material(path_b)
        mel = _mel()

        # --- Parameter diff ---
        params_a_data = json.loads(get_all_parameters(path_a))
        params_b_data = json.loads(get_all_parameters(path_b))

        params_a = {
            p["name"]: p
            for p in params_a_data.get("parameters", [])
        } if params_a_data.get("success") else {}
        params_b = {
            p["name"]: p
            for p in params_b_data.get("parameters", [])
        } if params_b_data.get("success") else {}

        only_a = sorted(set(params_a.keys()) - set(params_b.keys()))
        only_b = sorted(set(params_b.keys()) - set(params_a.keys()))
        common = sorted(set(params_a.keys()) & set(params_b.keys()))

        changed = []
        for name in common:
            pa, pb = params_a[name], params_b[name]
            if pa.get("type") != pb.get("type") or pa.get("default") != pb.get("default"):
                changed.append({
                    "name": name,
                    "a": {"type": pa.get("type"), "default": pa.get("default")},
                    "b": {"type": pb.get("type"), "default": pb.get("default")},
                })

        parameter_diff = {
            "only_a": only_a,
            "only_b": only_b,
            "changed": changed,
        }

        # --- Property / stats / expression diff (base materials only) ---
        property_diff = []
        stats_diff = {}
        expression_diff = {}

        both_base = not _is_material_instance(mat_a) and not _is_material_instance(mat_b)

        if both_base:
            # Property comparison
            for prop_name in ("blend_mode", "shading_model", "material_domain", "two_sided"):
                try:
                    val_a = mat_a.get_editor_property(prop_name)
                    val_b = mat_b.get_editor_property(prop_name)
                    str_a = _safe_enum_name(val_a) if not isinstance(val_a, bool) else str(val_a)
                    str_b = _safe_enum_name(val_b) if not isinstance(val_b, bool) else str(val_b)
                    if str_a != str_b:
                        property_diff.append({
                            "property": prop_name,
                            "a": str_a,
                            "b": str_b,
                        })
                except Exception:
                    pass

            # Stats comparison
            try:
                stat_fields = [
                    "num_vertex_shader_instructions",
                    "num_pixel_shader_instructions",
                    "num_samplers",
                    "num_vertex_texture_samples",
                    "num_pixel_texture_samples",
                    "num_virtual_texture_samples",
                    "num_uv_scalars",
                    "num_interpolator_scalars",
                ]
                sa = mel.get_statistics(mat_a)
                sb = mel.get_statistics(mat_b)
                for field in stat_fields:
                    va = int(getattr(sa, field))
                    vb = int(getattr(sb, field))
                    stats_diff[field] = {"a": va, "b": vb, "delta": vb - va}
            except Exception:
                pass

            # Expression count by class
            try:
                exprs_a_data = json.loads(scan_all_expressions(path_a))
                exprs_b_data = json.loads(scan_all_expressions(path_b))

                counts_a = {}
                counts_b = {}
                if exprs_a_data.get("success"):
                    for e in exprs_a_data.get("expressions", []):
                        cls = e.get("class", "Unknown")
                        counts_a[cls] = counts_a.get(cls, 0) + 1
                if exprs_b_data.get("success"):
                    for e in exprs_b_data.get("expressions", []):
                        cls = e.get("class", "Unknown")
                        counts_b[cls] = counts_b.get(cls, 0) + 1

                all_classes = sorted(set(counts_a.keys()) | set(counts_b.keys()))
                for cls in all_classes:
                    ca = counts_a.get(cls, 0)
                    cb = counts_b.get(cls, 0)
                    if ca != cb:
                        expression_diff[cls] = {"a": ca, "b": cb, "delta": cb - ca}
            except Exception:
                pass

        return json.dumps({
            "success": True,
            "path_a": path_a,
            "path_b": path_b,
            "parameter_diff": parameter_diff,
            "property_diff": property_diff,
            "stats_diff": stats_diff,
            "expression_diff": expression_diff,
        })
    except Exception as exc:
        return _error_json(exc)


# ===========================================================================
# WRITE HELPERS — Instance Editing + Graph Editing
# ===========================================================================

# ---------------------------------------------------------------------------
# W1. set_instance_parameter
# ---------------------------------------------------------------------------

def set_instance_parameter(asset_path, parameter_name, value, parameter_type=None):
    """Set a parameter override on a MaterialInstanceConstant.

    Parameters
    ----------
    asset_path : str
        Path to a MaterialInstanceConstant asset.
    parameter_name : str
        The parameter name to set.
    value
        The new value. Interpretation depends on *parameter_type*.
    parameter_type : str or None
        One of ``"Scalar"``, ``"Vector"``, ``"Texture"``, ``"StaticSwitch"``.
        If ``None``, auto-detected by checking which getter lists contain the name.

    Returns
    -------
    str
        JSON with old and new values.
    """
    try:
        mat = _load_material(asset_path)
        if not _is_material_instance(mat):
            return _error_json(f"Asset is not a MaterialInstanceConstant: {asset_path}")

        mel = _mel()

        # Auto-detect parameter type if not provided
        if parameter_type is None:
            type_getters = [
                ("Scalar", mel.get_scalar_parameter_names),
                ("Vector", mel.get_vector_parameter_names),
                ("Texture", mel.get_texture_parameter_names),
                ("StaticSwitch", mel.get_static_switch_parameter_names),
            ]
            for ptype, getter in type_getters:
                try:
                    names = getter(mat)
                    if parameter_name in [str(n) for n in names]:
                        parameter_type = ptype
                        break
                except Exception:
                    continue
            if parameter_type is None:
                return _error_json(
                    f"Parameter '{parameter_name}' not found on {asset_path}"
                )

        parameter_type_upper = parameter_type.upper()

        if parameter_type_upper == "SCALAR":
            old_value = mel.get_material_instance_scalar_parameter_value(mat, parameter_name)
            new_val = float(value)
            mel.set_material_instance_scalar_parameter_value(mat, parameter_name, new_val)
            old_repr = float(old_value)
            new_repr = new_val

        elif parameter_type_upper == "VECTOR":
            old_lc = mel.get_material_instance_vector_parameter_value(mat, parameter_name)
            old_repr = {"r": float(old_lc.r), "g": float(old_lc.g),
                        "b": float(old_lc.b), "a": float(old_lc.a)}
            if isinstance(value, dict):
                lc = unreal.LinearColor(
                    r=float(value.get("r", 0)),
                    g=float(value.get("g", 0)),
                    b=float(value.get("b", 0)),
                    a=float(value.get("a", 1)),
                )
            else:
                return _error_json("Vector value must be a dict with r/g/b/a keys")
            mel.set_material_instance_vector_parameter_value(mat, parameter_name, lc)
            new_repr = {"r": float(lc.r), "g": float(lc.g),
                        "b": float(lc.b), "a": float(lc.a)}

        elif parameter_type_upper == "TEXTURE":
            old_tex = mel.get_material_instance_texture_parameter_value(mat, parameter_name)
            old_repr = str(old_tex.get_path_name()) if old_tex else None
            tex = _eal().load_asset(str(value))
            if tex is None:
                return _error_json(f"Texture asset not found: {value}")
            mel.set_material_instance_texture_parameter_value(mat, parameter_name, tex)
            new_repr = str(value)

        elif parameter_type_upper == "STATICSWITCH":
            old_value = mel.get_material_instance_static_switch_parameter_value(
                mat, parameter_name
            )
            old_repr = bool(old_value)
            new_val = bool(value) if isinstance(value, bool) else str(value).lower() in (
                "true", "1", "yes"
            )
            mel.set_material_instance_static_switch_parameter_value(
                mat, parameter_name, new_val
            )
            new_repr = new_val

        else:
            return _error_json(f"Unknown parameter_type: {parameter_type}")

        mel.update_material_instance(mat)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "parameter_name": parameter_name,
            "parameter_type": parameter_type,
            "old_value": old_repr,
            "new_value": new_repr,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# W2. create_expression
# ---------------------------------------------------------------------------

def create_expression(asset_path, expression_class, node_pos_x=0, node_pos_y=0,
                      properties=None):
    """Create a new material expression node in a base material.

    Parameters
    ----------
    asset_path : str
        Path to a base Material asset.
    expression_class : str
        Short class name (e.g. ``"Multiply"``). Prefixed with ``MaterialExpression`` automatically.
    node_pos_x, node_pos_y : int
        Editor graph position.
    properties : dict or None
        Optional dict of editor properties to set on the new node.

    Returns
    -------
    str
        JSON with the created expression info.
    """
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json(
                "Cannot create expressions on a MaterialInstanceConstant. "
                "Use a base Material."
            )

        # Resolve expression class
        full_class_name = f"MaterialExpression{expression_class}"
        expr_class = getattr(unreal, full_class_name, None)
        if expr_class is None:
            return _error_json(f"Unknown expression class: {full_class_name}")

        expr = _mel().create_material_expression(
            mat, expr_class, int(node_pos_x), int(node_pos_y)
        )

        # Set optional properties
        failed_props = {}
        if properties:
            for prop_name, prop_value in properties.items():
                try:
                    expr.set_editor_property(prop_name, prop_value)
                except Exception as prop_exc:
                    failed_props[prop_name] = str(prop_exc)

        result = {
            "success": True,
            "asset_path": asset_path,
            "expression_name": _expr_id(expr),
            "expression_class": expression_class,
            "position": {"x": int(node_pos_x), "y": int(node_pos_y)},
        }
        if failed_props:
            result["failed_properties"] = failed_props

        return json.dumps(result)
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# W3. delete_expression
# ---------------------------------------------------------------------------

def delete_expression(asset_path, expression_name):
    """Delete a material expression node from a base material.

    Parameters
    ----------
    asset_path : str
        Path to a base Material asset.
    expression_name : str
        The expression object name (e.g. ``"MaterialExpressionMultiply_0"``).
        The ``MaterialExpression`` prefix is added automatically if missing.

    Returns
    -------
    str
        JSON confirmation.
    """
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json(
                "Cannot delete expressions on a MaterialInstanceConstant."
            )

        full_path = _full_object_path(asset_path)

        if not expression_name.startswith("MaterialExpression"):
            expression_name = f"MaterialExpression{expression_name}"

        obj_path = f"{full_path}:{expression_name}"
        expr = unreal.find_object(None, obj_path)
        if expr is None:
            return _error_json(f"Expression not found: {obj_path}")

        _mel().delete_material_expression(mat, expr)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "deleted": expression_name,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# W4. connect_expressions
# ---------------------------------------------------------------------------

def connect_expressions(asset_path, from_expression, to_expression_or_property,
                        from_output="", to_input=""):
    """Connect two expression nodes, or connect an expression to a material property pin.

    Parameters
    ----------
    asset_path : str
        Path to a base Material asset.
    from_expression : str
        Source expression object name.
    to_expression_or_property : str
        Target expression name **or** material property label (e.g. ``"BaseColor"``).
    from_output : str
        Output pin name on the source expression (empty for default).
    to_input : str
        Input pin name on the target expression (empty for default).

    Returns
    -------
    str
        JSON with connection details.
    """
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json(
                "Cannot connect expressions on a MaterialInstanceConstant."
            )

        mel = _mel()
        full_path = _full_object_path(asset_path)

        # Resolve source expression
        from_name = from_expression
        if not from_name.startswith("MaterialExpression"):
            from_name = f"MaterialExpression{from_name}"
        from_expr = unreal.find_object(None, f"{full_path}:{from_name}")
        if from_expr is None:
            return _error_json(f"Source expression not found: {from_name}")

        # Build property lookup: lowercased label -> enum attr name
        prop_map = {label.lower(): attr for label, attr in _MATERIAL_PROPERTIES}
        target_lower = to_expression_or_property.lower()

        if target_lower in prop_map:
            # Connect to material property pin
            prop_enum = getattr(unreal.MaterialProperty, prop_map[target_lower])
            ok = mel.connect_material_property(from_expr, from_output, prop_enum)
            conn_str = f"{from_name}[{from_output}] -> {to_expression_or_property}"
            return json.dumps({
                "success": bool(ok),
                "asset_path": asset_path,
                "connection": conn_str,
                "type": "property",
            })
        else:
            # Connect to another expression
            to_name = to_expression_or_property
            if not to_name.startswith("MaterialExpression"):
                to_name = f"MaterialExpression{to_name}"
            to_expr = unreal.find_object(None, f"{full_path}:{to_name}")
            if to_expr is None:
                return _error_json(f"Target expression not found: {to_name}")

            ok = mel.connect_material_expressions(
                from_expr, from_output, to_expr, to_input
            )
            conn_str = (
                f"{from_name}[{from_output}] -> {to_name}[{to_input}]"
            )
            return json.dumps({
                "success": bool(ok),
                "asset_path": asset_path,
                "connection": conn_str,
                "type": "expression",
            })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# W5. set_property
# ---------------------------------------------------------------------------

def set_property(asset_path, property_name, value):
    """Set a top-level material property (blend mode, shading model, etc.).

    Parameters
    ----------
    asset_path : str
        Path to a base Material asset.
    property_name : str
        One of: ``blend_mode``, ``shading_model``, ``two_sided``,
        ``material_domain``, or ``usage_*`` (e.g. ``usage_skeletal_mesh``).
    value : str or bool
        For enum properties, the enum member name (e.g. ``"BLEND_MASKED"``).
        For ``two_sided``, a boolean.

    Returns
    -------
    str
        JSON with old and new values.
    """
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json(
                "Cannot set material properties on a MaterialInstanceConstant. "
                "Edit the parent material instead."
            )

        prop_lower = property_name.lower()

        if prop_lower == "blend_mode":
            old = _safe_enum_name(mat.get_editor_property("blend_mode"))
            new_enum = getattr(unreal.BlendMode, value.upper())
            mat.set_editor_property("blend_mode", new_enum)
            new_repr = _safe_enum_name(new_enum)

        elif prop_lower == "shading_model":
            old = _safe_enum_name(mat.get_editor_property("shading_model"))
            new_enum = getattr(unreal.MaterialShadingModel, value.upper())
            mat.set_editor_property("shading_model", new_enum)
            new_repr = _safe_enum_name(new_enum)

        elif prop_lower == "two_sided":
            old_val = mat.get_editor_property("two_sided")
            old = str(old_val)
            if isinstance(value, bool):
                new_val = value
            else:
                new_val = str(value).lower() in ("true", "1", "yes")
            mat.set_editor_property("two_sided", new_val)
            new_repr = str(new_val)

        elif prop_lower == "material_domain":
            old = _safe_enum_name(mat.get_editor_property("material_domain"))
            new_enum = getattr(unreal.MaterialDomain, value.upper())
            mat.set_editor_property("material_domain", new_enum)
            new_repr = _safe_enum_name(new_enum)

        elif prop_lower.startswith("usage_"):
            # e.g. usage_skeletal_mesh -> SKELETAL_MESH
            usage_suffix = prop_lower[len("usage_"):].upper()
            usage_enum = getattr(unreal.MaterialUsage, usage_suffix)
            # set_material_usage returns the old value; just call it
            old = "unknown"
            try:
                # Try to read the current usage flag
                old = str(mat.get_editor_property(property_name))
            except Exception:
                pass
            _mel().set_material_usage(mat, usage_enum, True)
            new_repr = str(value)

        else:
            return _error_json(f"Unsupported property: {property_name}")

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "property": property_name,
            "old_value": old,
            "new_value": new_repr,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# W6. recompile
# ---------------------------------------------------------------------------

def recompile(asset_path):
    """Recompile a base material's shader.

    Parameters
    ----------
    asset_path : str
        Path to a base Material asset.

    Returns
    -------
    str
        JSON confirmation.
    """
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json(
                "Cannot recompile a MaterialInstanceConstant directly. "
                "Recompile its parent material instead."
            )

        _mel().recompile_material(mat)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "recompiled": True,
        })
    except Exception as exc:
        return _error_json(exc)


# ---------------------------------------------------------------------------
# W7. layout_graph
# ---------------------------------------------------------------------------

def layout_graph(asset_path):
    """Auto-layout all expression nodes in a base material's graph.

    Parameters
    ----------
    asset_path : str
        Path to a base Material asset.

    Returns
    -------
    str
        JSON confirmation.
    """
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json(
                "Cannot layout expressions on a MaterialInstanceConstant."
            )

        _mel().layout_material_expressions(mat)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "laid_out": True,
        })
    except Exception as exc:
        return _error_json(exc)


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
                            downstream_connections.append({
                                "expression": _expr_id(expr),
                                "note": "This expression would be removed",
                            })
                            break
            except Exception:
                pass

        elif expression_name:
            full_path = _full_object_path(asset_path)
            if not expression_name.startswith("MaterialExpression"):
                expression_name = f"MaterialExpression{expression_name}"
            obj_path = f"{full_path}:{expression_name}"
            expr = unreal.find_object(None, obj_path)
            if expr is None:
                return _error_json(f"Expression not found: {expression_name}")

            for prop_label, prop_attr in _MATERIAL_PROPERTIES:
                try:
                    prop_enum = getattr(unreal.MaterialProperty, prop_attr)
                    node = mel.get_material_property_input_node(mat, prop_enum)
                    if node is not None:
                        downstream_connections.append({
                            "output_pin": prop_label,
                            "note": f"Output pin {prop_label} may depend on this expression",
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

            # Count overrides
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
            tex = _eal().load_asset(str(value))
            if tex is None:
                return _error_json(f"Texture not found: {value}")
            expr.set_editor_property(property_name, tex)
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
        JSON with mapping of original to duplicate names.
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

            try:
                inputs = mel.get_inputs_for_material_expression(mat, expr)
                for inp in inputs:
                    if inp is not None:
                        to_visit.append(inp)
            except Exception:
                pass

        # Duplicate each expression
        name_map = {}
        for expr in expressions_to_dup:
            dup = mel.duplicate_material_expression(mat, None, expr)
            if dup is not None:
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
                name_map[_expr_id(expr)] = _expr_id(dup)

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
                            out_name = ""
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
