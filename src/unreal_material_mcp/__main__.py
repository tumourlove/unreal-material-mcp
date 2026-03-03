"""Entry point for `python -m unreal_material_mcp` and `uvx unreal-material-mcp`."""

from __future__ import annotations

import argparse

from unreal_material_mcp import __version__


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="unreal-material-mcp",
        description="Material graph intelligence for Unreal Engine AI development.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    args = parser.parse_args()
    _run_server()


def _run_server() -> None:
    from unreal_material_mcp.server import main
    main()


if __name__ == "__main__":
    cli()
