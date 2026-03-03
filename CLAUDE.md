# CLAUDE.md — unreal-material-mcp

## Project Overview

**unreal-material-mcp** — Material graph intelligence for Unreal Engine AI development.

An MCP server that inspects UE material graphs via the editor Python bridge. Read material attributes, parameters, expression nodes, connection graphs, and search across materials.

**Complements** (does not replace):
- `unreal-source-mcp` — Engine-level source intelligence
- `unreal-project-mcp` — Project-level source intelligence
- `unreal-editor-mcp` — Build diagnostics and editor log tools
- `unreal-blueprint-mcp` — Blueprint graph reading
- `unreal-config-mcp` — Config/INI intelligence

**We provide:** Material graph inspection — expressions, connections, parameters, attributes.

## Tech Stack

- **Language:** Python 3.11+
- **MCP SDK:** `mcp` Python package (FastMCP)
- **Distribution:** PyPI via `uvx unreal-material-mcp`
- **Package manager:** `uv` (for dev and build)

## Project Structure

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
        └── test_server.py              # 14 tests (mocked bridge)

## Build & Run

```bash
uv sync                                    # Install deps
uv run pytest tests/ -v                    # Run tests
uv run python -m unreal_material_mcp       # Run MCP server
```

## MCP Configuration (for Claude Code)

```json
{
  "mcpServers": {
    "unreal-material": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/tumourlove/unreal-material-mcp.git", "unreal-material-mcp"],
      "env": {
        "UE_PROJECT_PATH": "D:/Unreal Projects/Leviathan"
      }
    }
  }
}
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `UE_PROJECT_PATH` | Path to UE project root (contains .uproject) — required |
| `UE_EDITOR_PYTHON_PORT` | TCP port for command connection (default: 6776) |
| `UE_MULTICAST_GROUP` | UDP multicast group for discovery (default: 239.0.0.1) |
| `UE_MULTICAST_PORT` | UDP multicast port (default: 6766) |
| `UE_MULTICAST_BIND` | Multicast bind address (default: 127.0.0.1) |

## MCP Tools (5)

| Tool | Purpose |
|------|---------|
| `get_material_info` | Material attributes: blend mode, shading model, domain, usage flags, expression count |
| `get_material_parameters` | All parameters (scalar, vector, texture, static switch) with defaults |
| `get_material_expressions` | All expressions with types, names, positions, key properties. Optional class filter |
| `trace_material_connections` | Connection graph from a specific node or from material output pins |
| `search_materials` | Find materials by name, parameter name, expression type, or shading model |

## Architecture Notes

- **Helper module strategy** — `material_helpers.py` is uploaded to `{project}/Saved/MaterialMCP/` on first tool call. Tools send short scripts that import it. MD5 hash skips re-upload if unchanged.
- **Expression discovery** — brute-force scan using `find_object` with `ClassName_N` patterns across ~50 known expression classes. `get_num_material_expressions()` provides target count for early termination. 3-index lookahead handles gaps.
- **Editor bridge** — UE remote execution protocol: UDP multicast discovery → TCP command connection. Shared pattern across all sister servers.
- **No expression iteration API** — UE 5.7 has no `get_material_expression(mat, index)`. The `find_object` scan is the only way.
- **`connect_material_expressions` takes 4 args** — `(from, out_pin, to, in_pin)`. NO material argument. #1 gotcha.

## Coding Conventions

- **Lazy singletons** — `_get_bridge()` inits on first call, stored in module global
- **`_reset_state()`** — every module with singletons exposes this for test teardown
- **Mock-based testing** — tests mock EditorBridge; no real editor needed
- **Formatted string returns** — all tools return human-readable multi-line strings, not raw JSON
- Follow standard Python conventions: snake_case, type hints, docstrings on public functions
- Use `logging` module, not print statements
- Keep dependencies minimal — just `mcp>=1.0.0`
