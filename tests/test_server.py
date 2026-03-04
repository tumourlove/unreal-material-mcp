"""Tests for the MCP server helper upload infrastructure and tool output formatting."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from unreal_material_mcp import server


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset server singletons before and after each test."""
    server._reset_state()
    yield
    server._reset_state()


class TestEnsureHelperUploaded:
    """Tests for _ensure_helper_uploaded."""

    @patch.object(server, "_get_bridge")
    @patch.object(server, "_get_helper_source", return_value="# helper source code\n")
    def test_uploads_helper_via_bridge(self, mock_source, mock_get_bridge):
        """_ensure_helper_uploaded calls bridge.run_command to write the helper file."""
        mock_bridge = MagicMock()
        mock_get_bridge.return_value = mock_bridge

        server._project_path = "/tmp/TestProject"
        server._ensure_helper_uploaded()

        # Bridge should have been called exactly once with the upload script
        mock_bridge.run_command.assert_called_once()
        script = mock_bridge.run_command.call_args[0][0]

        # The script should create the target directory and write the file
        assert "os.makedirs" in script
        assert "MaterialMCP" in script
        assert "material_helpers.py" in script
        assert "helper source code" in script

        # Module state should be updated
        assert server._helper_uploaded is True
        assert server._helper_hash != ""

    @patch.object(server, "_get_bridge")
    @patch.object(server, "_get_helper_source", return_value="# helper source code\n")
    def test_skips_when_already_uploaded(self, mock_source, mock_get_bridge):
        """_ensure_helper_uploaded is a no-op when _helper_uploaded is True."""
        mock_bridge = MagicMock()
        mock_get_bridge.return_value = mock_bridge

        # Pre-set the uploaded flag
        server._helper_uploaded = True

        server._ensure_helper_uploaded()

        # Bridge should NOT have been called
        mock_bridge.run_command.assert_not_called()
        # Source should NOT have been read
        mock_source.assert_not_called()


# ---------------------------------------------------------------------------
# Helper for tool output formatting tests
# ---------------------------------------------------------------------------

def _setup_tool_mock(return_data: dict):
    """Configure server with mocked bridge returning *return_data* for tool calls.

    The bridge mock handles two sequential ``run_command`` calls:
    1. Helper upload  -> ``{"success": True, "output": "helper_uploaded"}``
    2. Tool script    -> ``{"success": True, "output": json.dumps(return_data)}``
    """
    server._project_path = "/tmp/TestProject"
    server._helper_uploaded = False
    server._helper_hash = ""

    mock_bridge = MagicMock()
    mock_bridge.run_command.side_effect = [
        {"success": True, "output": "helper_uploaded"},   # upload
        {"success": True, "output": json.dumps(return_data)},  # tool script
    ]
    server._bridge = mock_bridge


# ---------------------------------------------------------------------------
# Tool 1: get_material_info
# ---------------------------------------------------------------------------

class TestGetMaterialInfo:
    """Output formatting tests for get_material_info."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_base_material(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/Materials/M_Foo",
            "asset_type": "Material",
            "blend_mode": "Opaque",
            "shading_model": "DefaultLit",
            "material_domain": "Surface",
            "two_sided": False,
            "expression_count": 12,
            "usage_flags": {"bUsedWithStaticLighting": True},
        })
        result = server.get_material_info("/Game/Materials/M_Foo")

        assert "Blend Mode: Opaque" in result
        assert "Shading Model: DefaultLit" in result
        assert "Domain: Surface" in result
        assert "Expressions: 12" in result
        assert "bUsedWithStaticLighting" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_material_instance(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/Materials/MI_Foo",
            "asset_type": "MaterialInstanceConstant",
            "parent": "/Game/Materials/M_Base",
        })
        result = server.get_material_info("/Game/Materials/MI_Foo")

        assert "MaterialInstanceConstant" in result
        assert "Parent: /Game/Materials/M_Base" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_response(self, _src):
        _setup_tool_mock({"success": False, "error": "Asset not found"})
        result = server.get_material_info("/Game/Missing")

        assert "Error:" in result
        assert "Asset not found" in result


# ---------------------------------------------------------------------------
# Tool 2: get_material_parameters
# ---------------------------------------------------------------------------

class TestGetMaterialParameters:
    """Output formatting tests for get_material_parameters."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_parameters(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "parameters": [
                {"name": "Roughness", "type": "Scalar", "default": 0.5},
                {"name": "BaseColor", "type": "Vector", "default": {"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0}},
                {"name": "DiffuseTex", "type": "Texture", "default": "/Game/T_Diff"},
                {"name": "UseDetail", "type": "StaticSwitch", "default": True},
            ],
        })
        result = server.get_material_parameters("/Game/M_Foo")

        assert "[Scalar]" in result
        assert "Roughness = 0.5" in result
        assert "[Vector]" in result
        assert "BaseColor" in result
        assert "r=1.0" in result
        assert "[Texture]" in result
        assert "DiffuseTex" in result
        assert "[StaticSwitch]" in result
        assert "UseDetail" in result

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

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_no_parameters(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Empty",
            "parameters": [],
        })
        result = server.get_material_parameters("/Game/M_Empty")

        assert "No parameters" in result


# ---------------------------------------------------------------------------
# Tool 3: get_material_expressions
# ---------------------------------------------------------------------------

class TestGetMaterialExpressions:
    """Output formatting tests for get_material_expressions."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_expressions(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "expected_expression_count": 5,
            "found_expression_count": 5,
            "expressions": [
                {
                    "class": "ScalarParameter",
                    "name": "MaterialExpressionScalarParameter_0",
                    "position": {"x": -400, "y": 0},
                    "parameter_name": "Roughness",
                },
                {
                    "class": "Add",
                    "name": "MaterialExpressionAdd_0",
                    "position": {"x": -200, "y": 100},
                },
            ],
        })
        result = server.get_material_expressions("/Game/M_Foo")

        assert "[ScalarParameter]" in result
        assert "param=Roughness" in result
        assert "[Add]" in result
        assert "(-200, 100)" in result
        assert "5 found / 5 expected" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_missing_count_note(self, _src):
        """When expected > found the tool still formats without error."""
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "expected_expression_count": 10,
            "found_expression_count": 7,
            "expressions": [
                {"class": "Add", "name": "Add_0", "position": {"x": 0, "y": 0}},
            ],
        })
        result = server.get_material_expressions("/Game/M_Foo")

        assert "7 found / 10 expected" in result
        assert "[Add]" in result


# ---------------------------------------------------------------------------
# Tool 4: trace_material_connections
# ---------------------------------------------------------------------------

class TestTraceMaterialConnections:
    """Output formatting tests for trace_material_connections."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_output_pins(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "output_pins": {
                "BaseColor": {
                    "name": "TextureSample_0",
                    "position": {"x": -300, "y": 0},
                    "inputs": [],
                },
            },
        })
        result = server.trace_material_connections("/Game/M_Foo")

        assert "[BaseColor]" in result
        assert "TextureSample_0" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_specific_node(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "tree": {
                "name": "Add_0",
                "position": {"x": -200, "y": 0},
                "inputs": [
                    {
                        "input_name": "A",
                        "connected_node": {
                            "name": "Constant_0",
                            "position": {"x": -400, "y": 0},
                            "inputs": [],
                        },
                    },
                ],
            },
        })
        result = server.trace_material_connections(
            "/Game/M_Foo", expression_name="Add_0"
        )

        assert "Add_0" in result
        assert "Constant_0" in result
        assert "<- A:" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_cycle_detection(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "tree": {
                "name": "Add_0",
                "position": {"x": 0, "y": 0},
                "inputs": [
                    {
                        "input_name": "A",
                        "connected_node": {
                            "name": "Add_0",
                            "position": {"x": 0, "y": 0},
                            "cycle": True,
                        },
                    },
                ],
            },
        })
        result = server.trace_material_connections(
            "/Game/M_Foo", expression_name="Add_0"
        )

        assert "[CYCLE]" in result


# ---------------------------------------------------------------------------
# Tool 5: search_materials
# ---------------------------------------------------------------------------

class TestSearchMaterials:
    """Output formatting tests for search_materials."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_results(self, _src):
        _setup_tool_mock({
            "success": True,
            "base_path": "/Game/Materials",
            "filter_type": "name",
            "query": "Foo",
            "count": 2,
            "results": [
                {"asset_path": "/Game/Materials/M_Foo", "asset_name": "M_Foo", "class": "Material"},
                {"asset_path": "/Game/Materials/MI_FooInst", "asset_name": "MI_FooInst", "class": "MaterialInstanceConstant"},
            ],
        })
        result = server.search_materials("/Game/Materials", query="Foo")

        assert "Found: 2" in result
        assert "/Game/Materials/M_Foo" in result
        assert "/Game/Materials/MI_FooInst" in result
        assert "M_Foo" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_no_results(self, _src):
        _setup_tool_mock({
            "success": True,
            "base_path": "/Game/Materials",
            "filter_type": "name",
            "query": "Nonexistent",
            "count": 0,
            "results": [],
        })
        result = server.search_materials("/Game/Materials", query="Nonexistent")

        assert "Found: 0" in result


# ---------------------------------------------------------------------------
# Tool 6: get_material_stats
# ---------------------------------------------------------------------------

class TestGetMaterialStats:
    """Output formatting tests for get_material_stats."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_stats_with_warnings(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Heavy",
            "stats": {
                "num_vertex_shader_instructions": 50,
                "num_pixel_shader_instructions": 600,
                "num_samplers": 18,
                "num_pixel_texture_samples": 12,
                "num_vertex_texture_samples": 0,
                "num_virtual_texture_samples": 2,
                "num_uv_scalars": 4,
                "num_interpolator_scalars": 8,
            },
            "warnings": ["High sampler count", "High pixel shader instructions"],
        })
        result = server.get_material_stats("/Game/M_Heavy")

        assert "VS=50 PS=600" in result
        assert "Samplers: 18" in result
        assert "Warnings:" in result
        assert "High sampler count" in result

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

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_no_warnings(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Simple",
            "stats": {
                "num_vertex_shader_instructions": 20,
                "num_pixel_shader_instructions": 30,
                "num_samplers": 2,
                "num_pixel_texture_samples": 2,
                "num_vertex_texture_samples": 0,
                "num_virtual_texture_samples": 0,
                "num_uv_scalars": 1,
                "num_interpolator_scalars": 2,
            },
            "warnings": [],
        })
        result = server.get_material_stats("/Game/M_Simple")

        assert "No warnings" in result


# ---------------------------------------------------------------------------
# Tool 7: get_material_dependencies
# ---------------------------------------------------------------------------

class TestGetMaterialDependencies:
    """Output formatting tests for get_material_dependencies."""

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

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_empty_dependencies(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Empty",
            "textures": [],
            "functions": [],
            "parameter_sources": [],
        })
        result = server.get_material_dependencies("/Game/M_Empty")

        assert "(none)" in result


# ---------------------------------------------------------------------------
# Tool 8: inspect_material_function
# ---------------------------------------------------------------------------

class TestInspectMaterialFunction:
    """Output formatting tests for inspect_material_function."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_function(self, _src):
        _setup_tool_mock({
            "success": True,
            "function_path": "/Game/MF_Blend",
            "description": "Blends two inputs",
            "caption": "Custom Blend",
            "expression_count": 5,
            "inputs": [
                {"name": "Base", "type": "Float3"},
                {"name": "Detail", "type": "Float3"},
            ],
            "outputs": [
                {"name": "Result", "type": "Float3"},
            ],
            "expressions": [
                {"class": "FunctionInput", "name": "Input_0"},
                {"class": "FunctionOutput", "name": "Output_0"},
                {"class": "Lerp", "name": "Lerp_0"},
                {"class": "Multiply", "name": "Multiply_0"},
            ],
        })
        result = server.inspect_material_function("/Game/MF_Blend")

        assert "Description: Blends two inputs" in result
        assert "Inputs (2)" in result
        assert "Base (Float3)" in result
        assert "Outputs (1)" in result
        assert "Result (Float3)" in result
        assert "[Lerp]" in result
        assert "[Multiply]" in result
        # FunctionInput/FunctionOutput should be excluded from expressions
        assert "FunctionInput" not in result
        assert "FunctionOutput" not in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_expression_not_found(self, _src):
        _setup_tool_mock({
            "success": False,
            "error": "Expression 'MF_Missing' not found",
        })
        result = server.inspect_material_function("/Game/M_Foo", function_name="MF_Missing")

        assert "Error:" in result
        assert "not found" in result


# ---------------------------------------------------------------------------
# Tool 9: get_material_instance_chain
# ---------------------------------------------------------------------------

class TestGetMaterialInstanceChain:
    """Output formatting tests for get_material_instance_chain."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_chain(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/MI_Foo",
            "chain": [
                {
                    "asset_path": "/Game/MI_Foo",
                    "asset_type": "MaterialInstanceConstant",
                    "overrides": [
                        {"name": "Roughness", "value": 0.8},
                        {"name": "Color", "value": "(1,0,0,1)"},
                    ],
                },
                {
                    "asset_path": "/Game/M_Base",
                    "asset_type": "Material",
                    "blend_mode": "Opaque",
                    "shading_model": "DefaultLit",
                },
            ],
            "children": [],
        })
        result = server.get_material_instance_chain("/Game/MI_Foo")

        assert "[0]" in result
        assert "[1]" in result
        assert "Roughness = 0.8" in result
        assert "Blend Mode: Opaque" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_with_children(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/MI_Foo",
            "chain": [
                {
                    "asset_path": "/Game/MI_Foo",
                    "asset_type": "MaterialInstanceConstant",
                    "overrides": [],
                },
            ],
            "children": ["/Game/MI_Child1", "/Game/MI_Child2"],
        })
        result = server.get_material_instance_chain("/Game/MI_Foo")

        assert "Children (2)" in result
        assert "/Game/MI_Child1" in result
        assert "/Game/MI_Child2" in result


# ---------------------------------------------------------------------------
# Tool 10: compare_materials
# ---------------------------------------------------------------------------

class TestCompareMaterials:
    """Output formatting tests for compare_materials."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_diff(self, _src):
        _setup_tool_mock({
            "success": True,
            "path_a": "/Game/M_A",
            "path_b": "/Game/M_B",
            "only_a": ["Metallic"],
            "only_b": ["Emissive"],
            "changed": ["Roughness"],
            "property_diff": {
                "blend_mode": {"a": "Opaque", "b": "Translucent"},
            },
            "stats_diff": {
                "ps_instructions": {"a": 50, "b": 120},
            },
            "expression_diff": {
                "Add": {"a": 3, "b": 5},
            },
        })
        result = server.compare_materials("/Game/M_A", "/Game/M_B")

        assert "- Metallic" in result
        assert "+ Emissive" in result
        assert "~ Roughness" in result
        assert "blend_mode" in result
        assert "Opaque -> Translucent" in result
        assert "ps_instructions" in result
        assert "Add" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_identical_materials(self, _src):
        _setup_tool_mock({
            "success": True,
            "path_a": "/Game/M_A",
            "path_b": "/Game/M_B",
            "only_a": [],
            "only_b": [],
            "changed": [],
            "property_diff": {},
            "stats_diff": {},
            "expression_diff": {},
        })
        result = server.compare_materials("/Game/M_A", "/Game/M_B")

        assert "identical" in result


# ---------------------------------------------------------------------------
# Tool 11: set_material_instance_parameter
# ---------------------------------------------------------------------------

class TestSetMaterialInstanceParameter:
    """Output formatting tests for set_material_instance_parameter."""

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
        result = server.set_material_instance_parameter(
            "/Game/MI_Foo", "Roughness", "0.8"
        )

        assert "Roughness" in result
        assert "0.5" in result
        assert "0.8" in result
        assert "Updated successfully" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_not_instance(self, _src):
        _setup_tool_mock({
            "success": False,
            "error": "Asset is not a MaterialInstanceConstant",
        })
        result = server.set_material_instance_parameter(
            "/Game/M_Base", "Roughness", "0.5"
        )

        assert "Error:" in result
        assert "MaterialInstanceConstant" in result


# ---------------------------------------------------------------------------
# Tool 12: create_material_expression
# ---------------------------------------------------------------------------

class TestCreateMaterialExpression:
    """Output formatting tests for create_material_expression."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_created(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "expression_name": "MaterialExpressionScalarParameter_0",
            "expression_class": "ScalarParameter",
            "position": {"x": -400, "y": 200},
        })
        result = server.create_material_expression(
            "/Game/M_Foo", "ScalarParameter", node_pos_x=-400, node_pos_y=200
        )

        assert "Created: MaterialExpressionScalarParameter_0" in result
        assert "ScalarParameter" in result
        assert "(-400, 200)" in result
        assert "/Game/M_Foo" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_bad_class(self, _src):
        _setup_tool_mock({
            "success": False,
            "error": "Unknown expression class 'FakeNode'",
        })
        result = server.create_material_expression("/Game/M_Foo", "FakeNode")

        assert "Error:" in result
        assert "Unknown expression class" in result


# ---------------------------------------------------------------------------
# Tool 13: delete_material_expression
# ---------------------------------------------------------------------------

class TestDeleteMaterialExpression:
    """Output formatting tests for delete_material_expression."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_deleted(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "expression_name": "MaterialExpressionAdd_0",
        })
        result = server.delete_material_expression("/Game/M_Foo", "MaterialExpressionAdd_0")

        assert "Deleted:" in result
        assert "MaterialExpressionAdd_0" in result
        assert "/Game/M_Foo" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_not_found(self, _src):
        _setup_tool_mock({
            "success": False,
            "error": "Expression 'Missing_0' not found",
        })
        result = server.delete_material_expression("/Game/M_Foo", "Missing_0")

        assert "Error:" in result
        assert "not found" in result


# ---------------------------------------------------------------------------
# Tool 14: connect_material_expressions
# ---------------------------------------------------------------------------

class TestConnectMaterialExpressions:
    """Output formatting tests for connect_material_expressions."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_expression_to_expression(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "connection_string": "Multiply_0:Out -> Add_0:A",
            "connection_type": "expression",
        })
        result = server.connect_material_expressions(
            "/Game/M_Foo", "Multiply_0", "Add_0",
            from_output="Out", to_input="A",
        )

        assert "Connected:" in result
        assert "Multiply_0:Out -> Add_0:A" in result
        assert "Type: expression" in result
        assert "/Game/M_Foo" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_expression_to_property(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "connection_string": "TextureSample_0:RGB -> BaseColor",
            "connection_type": "property",
        })
        result = server.connect_material_expressions(
            "/Game/M_Foo", "TextureSample_0", "BaseColor",
            from_output="RGB",
        )

        assert "Connected:" in result
        assert "Type: property" in result
        assert "BaseColor" in result


# ---------------------------------------------------------------------------
# Tool 15: set_material_property
# ---------------------------------------------------------------------------

class TestSetMaterialProperty:
    """Output formatting tests for set_material_property."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_property_change(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
            "property_name": "blend_mode",
            "old_value": "Opaque",
            "new_value": "Translucent",
        })
        result = server.set_material_property("/Game/M_Foo", "blend_mode", '"Translucent"')

        assert "blend_mode" in result
        assert "Opaque" in result
        assert "Translucent" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_error_bad_property(self, _src):
        _setup_tool_mock({
            "success": False,
            "error": "Unknown property 'fake_prop'",
        })
        result = server.set_material_property("/Game/M_Foo", "fake_prop", "1")

        assert "Error:" in result
        assert "Unknown property" in result


# ---------------------------------------------------------------------------
# Tool 16 & 17: recompile_material & layout_material_graph
# ---------------------------------------------------------------------------

class TestRecompileAndLayout:
    """Output formatting tests for recompile_material and layout_material_graph."""

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_recompile(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
        })
        result = server.recompile_material("/Game/M_Foo")

        assert "Recompiled" in result
        assert "/Game/M_Foo" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_layout(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/M_Foo",
        })
        result = server.layout_material_graph("/Game/M_Foo")

        assert "Layout applied" in result
        assert "/Game/M_Foo" in result

    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_recompile_error_on_instance(self, _src):
        _setup_tool_mock({
            "success": False,
            "error": "Cannot recompile a MaterialInstanceConstant",
        })
        result = server.recompile_material("/Game/MI_Foo")

        assert "Error:" in result
        assert "MaterialInstanceConstant" in result


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


# ---------------------------------------------------------------------------
# Tool 19: find_breaking_changes
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool 20: find_material_function_usage
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool 21: search_material_instances
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool 22: set_expression_property
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool 23: duplicate_expression_subgraph
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool 24: manage_material_parameter
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool 25: rename_parameter_cascade
# ---------------------------------------------------------------------------

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
