# unreal-material-mcp

Material graph intelligence and editing for Unreal Engine AI development via [Model Context Protocol](https://modelcontextprotocol.io/).

Gives AI assistants full access to UE material graphs — read attributes, parameters, expressions, and connections; analyze performance and dependencies; compare materials; edit material instances; and manipulate material graphs (create/delete/connect expressions, set properties, recompile).

## Why?

Materials are one of the most complex systems in Unreal — deeply nested expression graphs, layered parameter inheritance, and opaque shader compilation. AI assistants can read C++ and Blueprints, but they can't see inside material graphs or understand how expressions connect. This server exposes the full material graph as structured data and provides editing tools so AI agents can inspect, analyze, and modify materials programmatically.

**Complements** (does not replace):
- [unreal-source-mcp](https://github.com/tumourlove/unreal-source-mcp) — Engine-level source intelligence (full UE C++ and HLSL)
- [unreal-project-mcp](https://github.com/tumourlove/unreal-project-mcp) — Project-level source intelligence (your C++ code)
- [unreal-editor-mcp](https://github.com/tumourlove/unreal-editor-mcp) — Build diagnostics and editor log tools (Live Coding, error parsing, log search)
- [unreal-blueprint-mcp](https://github.com/tumourlove/unreal-blueprint-mcp) — Blueprint graph reading (nodes, pins, connections, execution flow)
- [unreal-config-mcp](https://github.com/tumourlove/unreal-config-mcp) — Config/INI intelligence (resolve inheritance chains, search settings, diff from defaults, explain CVars)
- [unreal-animation-mcp](https://github.com/tumourlove/unreal-animation-mcp) — Animation data inspector and editor (sequences, montages, blend spaces, ABPs, skeletons, 62 tools)
- [unreal-api-mcp](https://github.com/nicobailon/unreal-api-mcp) by [Nico Bailon](https://github.com/nicobailon) — API surface lookup (signatures, #include paths, deprecation warnings)

Together these servers give AI agents full-stack UE understanding: engine internals, API surface, your project code, build/runtime feedback, Blueprint graph data, config/INI intelligence, material graph inspection + editing, and animation data inspection + editing.

## Prerequisites

- **Python Remote Execution** must be enabled in the editor: **Edit > Project Settings** > search "remote" > under **Python Remote Execution**, check **"Enable Remote Execution?"**

## Quick Start

### Install from GitHub

```bash
uvx --from git+https://github.com/tumourlove/unreal-material-mcp.git unreal-material-mcp
```

### Claude Code Configuration

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "unreal-material": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/tumourlove/unreal-material-mcp.git", "unreal-material-mcp"],
      "env": {
        "UE_PROJECT_PATH": "D:/Unreal Projects/MyProject"
      }
    }
  }
}
```

Or run from local source during development:

```json
{
  "mcpServers": {
    "unreal-material": {
      "command": "uv",
      "args": ["run", "--directory", "C:/Projects/unreal-material-mcp", "unreal-material-mcp"],
      "env": {
        "UE_PROJECT_PATH": "D:/Unreal Projects/MyProject"
      }
    }
  }
}
```

## Tools

### Read-Only Inspection (5)

| Tool | Description |
|------|-------------|
| `get_material_info` | Material attributes: blend mode, shading model, domain, usage flags, expression count |
| `get_material_parameters` | All parameters (scalar, vector, texture, static switch) with defaults + static switch values/controls |
| `get_material_expressions` | All expressions with types, names, positions, key properties. Optional class filter |
| `trace_material_connections` | Connection graph from a specific node or from material output pins |
| `search_materials` | Find materials by name, parameter name, expression type, or shading model |

### Read-Only Analysis (8)

| Tool | Description |
|------|-------------|
| `get_material_stats` | Shader instruction counts, sampler usage, texture samples + compile status/errors + diagnostic warnings |
| `get_material_dependencies` | Textures used (with sizes/formats), material functions referenced, parameter source tracing |
| `inspect_material_function` | Scan expressions inside a material function (from a material's function call or direct path) |
| `get_material_instance_chain` | Walk parent chain from instance to root material, show overrides, list children |
| `compare_materials` | Diff two materials: parameters, properties, stats, expression counts |
| `find_material_references` | Reverse lookup: find all assets referencing a material |
| `find_breaking_changes` | Detect parameter removals/renames that would break child instances |
| `find_material_function_usage` | Find all materials using a specific material function, with call chains |

### Search (2)

| Tool | Description |
|------|-------------|
| `search_material_instances` | Search/filter material instances by parent, dead references, parameter overrides |
| `batch_update_materials` | Batch update materials: swap textures, set parameters, or set attributes |

### Instance Editing (3)

| Tool | Description |
|------|-------------|
| `set_material_instance_parameter` | Set scalar/vector/texture/static switch overrides on a MaterialInstanceConstant |
| `create_material_instance` | Create a new MaterialInstanceConstant from a parent material |
| `reparent_material_instance` | Reparent a MaterialInstanceConstant to a different parent |

### Graph Editing (10)

| Tool | Description |
|------|-------------|
| `create_material_expression` | Create a new expression node with optional position and properties |
| `delete_material_expression` | Delete an expression node (auto-disconnects, warns about downstream disconnections) |
| `connect_material_expressions` | Connect two expressions or connect to a material output pin (warns if overwriting existing connection) |
| `set_material_property` | Set blend mode, shading model, two-sided, domain, or usage flags |
| `set_expression_property` | Set any editor property on an existing expression node |
| `recompile_material` | Recompile a material after graph changes |
| `layout_material_graph` | Auto-layout all expression nodes in a grid pattern |
| `duplicate_expression_subgraph` | Deep-copy an expression and its upstream chain into same or different material |
| `manage_material_parameter` | Add, remove, or rename parameter expressions |
| `rename_parameter_cascade` | Rename a parameter across a material and all its child instances |

## Asset Path Format

Tools accept Unreal asset paths (no file extension):

| Location | Format | Example |
|----------|--------|---------|
| Project `Content/` | `/Game/Path/To/Material` | `/Game/Materials/M_Master` |
| Project `Plugins/` | `/PluginName/PluginName/Path/To/Asset` | `/MyPlugin/MyPlugin/Materials/M_Base` |
| Engine plugins | `/PluginName/Path/To/Asset` | `/Engine/Materials/M_Default` |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `UE_PROJECT_PATH` | Yes | Path to the UE project root (containing the .uproject file) |
| `UE_EDITOR_PYTHON_PORT` | No | TCP port for command connection (default: `6776`) |
| `UE_MULTICAST_GROUP` | No | UDP multicast group for editor discovery (default: `239.0.0.1`) |
| `UE_MULTICAST_PORT` | No | UDP multicast port for editor discovery (default: `6766`) |
| `UE_MULTICAST_BIND` | No | Multicast bind address (default: `127.0.0.1`) |

## How It Works

1. **Editor Discovery** — Discovers the running UE editor via UDP multicast (the same protocol as UE's built-in `remote_execution.py`). Opens a TCP command channel to execute Python in the editor.

2. **Helper Module** — On first tool call, uploads `material_helpers.py` to `{project}/Saved/MaterialMCP/`. Tools send short scripts that import it. MD5 hash skips re-upload if unchanged.

3. **Expression Discovery** — UE has no `get_material_expression(mat, index)` API. The server uses brute-force `find_object` scanning across ~100 known expression classes with early termination when the target count is reached.

4. **Serving** — FastMCP server exposes 28 tools over stdio. Claude Code manages the server lifecycle automatically.

**No database** — all data comes live from the running editor. The server is stateless; materials are read on demand.

## Adding to Your Project's CLAUDE.md

```markdown
## Material Graph Intelligence (unreal-material MCP)

Use `unreal-material` MCP tools to inspect and edit material graphs. Requires
**Python Remote Execution** enabled in editor.

| Tool | When |
|------|------|
| `get_material_info` | Get material attributes (blend mode, shading model, domain) |
| `get_material_parameters` | List all parameters with defaults and values |
| `get_material_expressions` | List all expression nodes in a material graph |
| `trace_material_connections` | Trace the connection graph from a node or output pin |
| `get_material_stats` | Check shader instruction counts and compile status |
| `compare_materials` | Diff two materials side by side |
| `create_material_expression` | Add a new expression node to a material graph |
| `connect_material_expressions` | Wire two nodes together (warns if overwriting) |
| `delete_material_expression` | Remove a node (warns about downstream disconnections) |
| `recompile_material` | Recompile after graph changes |
| `set_material_instance_parameter` | Set parameter overrides on instances |

**Rules:**
- Graph editing only works on base Materials, not MaterialInstanceConstants
- Always call `recompile_material` after batching graph changes
- `connect_material_expressions` takes 4 args (from, out_pin, to, in_pin) — no material arg
```

## Development

```bash
# Clone and install
git clone https://github.com/tumourlove/unreal-material-mcp.git
cd unreal-material-mcp
uv sync

# Run tests (60 tests)
uv run pytest -v

# Run server locally
uv run unreal-material-mcp
```

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Unreal Engine 5.x with Python plugin and Remote Execution enabled

## License

MIT
