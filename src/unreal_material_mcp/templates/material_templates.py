"""Material graph templates — each returns a graph_spec dict for build_material_graph."""


def noise_blend(params=None):
    """Two-input blend driven by noise."""
    p = params or {}
    scale = p.get("scale", 10.0)
    contrast = p.get("contrast", 2.0)

    return {
        "nodes": [
            {"id": "noise", "class": "Noise", "pos": [-800, 0]},
            {"id": "multiply", "class": "Multiply", "pos": [-600, 0]},
            {"id": "contrast_const", "class": "Constant", "pos": [-800, 100],
             "props": {"R": contrast}},
            {"id": "saturate", "class": "Saturate", "pos": [-400, 0]},
            {"id": "lerp", "class": "LinearInterpolate", "pos": [-200, 0]},
            {"id": "input_a", "class": "VectorParameter", "pos": [-600, -200],
             "props": {"ParameterName": p.get("param_a", "Blend Color A"),
                       "DefaultValue": "(R=0.8,G=0.2,B=0.1,A=1.0)"}},
            {"id": "input_b", "class": "VectorParameter", "pos": [-600, -100],
             "props": {"ParameterName": p.get("param_b", "Blend Color B"),
                       "DefaultValue": "(R=0.2,G=0.4,B=0.6,A=1.0)"}},
            {"id": "scale_param", "class": "ScalarParameter", "pos": [-1000, 0],
             "props": {"ParameterName": "Noise Scale", "DefaultValue": str(scale)}},
        ],
        "connections": [
            {"from": "noise", "from_pin": "", "to": "multiply", "to_pin": "A"},
            {"from": "contrast_const", "from_pin": "", "to": "multiply", "to_pin": "B"},
            {"from": "multiply", "from_pin": "", "to": "saturate", "to_pin": ""},
            {"from": "saturate", "from_pin": "", "to": "lerp", "to_pin": "Alpha"},
            {"from": "input_a", "from_pin": "", "to": "lerp", "to_pin": "A"},
            {"from": "input_b", "from_pin": "", "to": "lerp", "to_pin": "B"},
        ],
        "outputs": [],
        "_output_node": "lerp",
        "_output_pin": "",
        "_exposed_params": ["Blend Color A", "Blend Color B", "Noise Scale"],
    }


def pbr_texture_set(params=None):
    """Full PBR texture wiring: albedo, normal, roughness, AO."""
    p = params or {}
    tiling = p.get("tiling", 1.0)
    prefix = p.get("param_prefix", "")

    return {
        "nodes": [
            {"id": "tiling", "class": "ScalarParameter", "pos": [-1200, 0],
             "props": {"ParameterName": f"{prefix}Tiling", "DefaultValue": str(tiling)}},
            {"id": "texcoord", "class": "TextureCoordinate", "pos": [-1000, 0]},
            {"id": "multiply_uv", "class": "Multiply", "pos": [-800, 0]},
            {"id": "albedo", "class": "TextureSampleParameter2D", "pos": [-500, -400],
             "props": {"ParameterName": f"{prefix}Albedo"}},
            {"id": "normal", "class": "TextureSampleParameter2D", "pos": [-500, -200],
             "props": {"ParameterName": f"{prefix}Normal"}},
            {"id": "roughness", "class": "TextureSampleParameter2D", "pos": [-500, 0],
             "props": {"ParameterName": f"{prefix}Roughness"}},
            {"id": "ao", "class": "TextureSampleParameter2D", "pos": [-500, 200],
             "props": {"ParameterName": f"{prefix}AO"}},
        ],
        "connections": [
            {"from": "tiling", "from_pin": "", "to": "multiply_uv", "to_pin": "A"},
            {"from": "texcoord", "from_pin": "", "to": "multiply_uv", "to_pin": "B"},
            {"from": "multiply_uv", "from_pin": "", "to": "albedo", "to_pin": "UVs"},
            {"from": "multiply_uv", "from_pin": "", "to": "normal", "to_pin": "UVs"},
            {"from": "multiply_uv", "from_pin": "", "to": "roughness", "to_pin": "UVs"},
            {"from": "multiply_uv", "from_pin": "", "to": "ao", "to_pin": "UVs"},
        ],
        "outputs": [
            {"from": "albedo", "from_pin": "RGB", "to_property": "BaseColor"},
            {"from": "normal", "from_pin": "RGB", "to_property": "Normal"},
            {"from": "roughness", "from_pin": "R", "to_property": "Roughness"},
            {"from": "ao", "from_pin": "R", "to_property": "AmbientOcclusion"},
        ],
        "_exposed_params": [f"{prefix}Tiling", f"{prefix}Albedo", f"{prefix}Normal",
                           f"{prefix}Roughness", f"{prefix}AO"],
    }


def fresnel_glow(params=None):
    """Fresnel-driven emissive effect."""
    p = params or {}
    return {
        "nodes": [
            {"id": "fresnel", "class": "Fresnel", "pos": [-600, 0]},
            {"id": "power_param", "class": "ScalarParameter", "pos": [-800, 0],
             "props": {"ParameterName": "Fresnel Power", "DefaultValue": str(p.get("power", 3.0))}},
            {"id": "color_param", "class": "VectorParameter", "pos": [-600, -200],
             "props": {"ParameterName": "Glow Color",
                       "DefaultValue": "(R=0.0,G=0.5,B=1.0,A=1.0)"}},
            {"id": "intensity", "class": "ScalarParameter", "pos": [-600, -100],
             "props": {"ParameterName": "Glow Intensity", "DefaultValue": str(p.get("intensity", 5.0))}},
            {"id": "multiply_color", "class": "Multiply", "pos": [-400, -150]},
            {"id": "multiply_fresnel", "class": "Multiply", "pos": [-200, 0]},
        ],
        "connections": [
            {"from": "color_param", "from_pin": "", "to": "multiply_color", "to_pin": "A"},
            {"from": "intensity", "from_pin": "", "to": "multiply_color", "to_pin": "B"},
            {"from": "multiply_color", "from_pin": "", "to": "multiply_fresnel", "to_pin": "A"},
            {"from": "fresnel", "from_pin": "", "to": "multiply_fresnel", "to_pin": "B"},
        ],
        "outputs": [
            {"from": "multiply_fresnel", "from_pin": "", "to_property": "EmissiveColor"},
        ],
        "_output_node": "multiply_fresnel",
        "_exposed_params": ["Fresnel Power", "Glow Color", "Glow Intensity"],
    }


TEMPLATES = {
    "noise_blend": noise_blend,
    "pbr_texture_set": pbr_texture_set,
    "fresnel_glow": fresnel_glow,
}


def get_template_spec(template_name, params=None):
    """Get a graph spec from a template name."""
    func = TEMPLATES.get(template_name)
    if func is None:
        return None
    return func(params)


def list_templates():
    """Return list of available template names with descriptions."""
    return {name: func.__doc__.strip().split('\n')[0] for name, func in TEMPLATES.items()}
