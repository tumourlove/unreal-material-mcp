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
    "Comment", "NamedRerouteDeclaration", "NamedRerouteUsage",
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
                params.append({
                    "name": name_str,
                    "type": "StaticSwitch",
                    "default": default,
                })
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
