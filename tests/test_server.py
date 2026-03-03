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
