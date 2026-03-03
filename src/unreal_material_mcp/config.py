"""Configuration for unreal-material-mcp."""

import os

UE_PROJECT_PATH = os.environ.get("UE_PROJECT_PATH", "")
UE_EDITOR_PYTHON_PORT = int(os.environ.get("UE_EDITOR_PYTHON_PORT", "6776"))
UE_MULTICAST_GROUP = os.environ.get("UE_MULTICAST_GROUP", "239.0.0.1")
UE_MULTICAST_PORT = int(os.environ.get("UE_MULTICAST_PORT", "6766"))
UE_MULTICAST_BIND = os.environ.get("UE_MULTICAST_BIND", "127.0.0.1")
