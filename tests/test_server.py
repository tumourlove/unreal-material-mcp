"""Tests for the MCP server helper upload infrastructure."""

from __future__ import annotations

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
