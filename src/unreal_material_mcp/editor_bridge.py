"""Editor bridge: detect UE editor and execute Python commands via remote execution protocol."""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import time
import uuid

from unreal_material_mcp.config import (
    UE_EDITOR_PYTHON_PORT,
    UE_MULTICAST_BIND,
    UE_MULTICAST_GROUP,
    UE_MULTICAST_PORT,
)

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
PROTOCOL_MAGIC = "ue_py"
_RECV_BUFFER = 8192
_DISCOVERY_TIMEOUT = 5.0


class EditorNotRunning(Exception):
    """Raised when trying to communicate with an editor that isn't running."""


def _build_message(
    type_: str, source: str, dest: str | None = None, data: dict | None = None,
) -> str:
    """Build a JSON protocol message."""
    msg: dict = {
        "version": PROTOCOL_VERSION,
        "magic": PROTOCOL_MAGIC,
        "type": type_,
        "source": source,
    }
    if dest:
        msg["dest"] = dest
    if data:
        msg["data"] = data
    return json.dumps(msg, ensure_ascii=False)


def _parse_message(raw: str) -> dict | None:
    """Parse and validate a JSON protocol message. Returns None if invalid."""
    try:
        msg = json.loads(raw)
        if msg.get("version") != PROTOCOL_VERSION:
            return None
        if msg.get("magic") != PROTOCOL_MAGIC:
            return None
        return msg
    except (json.JSONDecodeError, KeyError):
        return None


class EditorBridge:
    """Manages communication with a running UE editor instance."""

    def __init__(self, auto_connect: bool = True) -> None:
        self._node_id = str(uuid.uuid4())
        self._remote_node_id: str | None = None
        self._command_socket: socket.socket | None = None
        self._connected = False
        if auto_connect:
            try:
                self.connect()
            except Exception:
                logger.info("Editor not available, bridge in disconnected mode")

    def is_editor_running(self) -> bool:
        """Check if UnrealEditor.exe is running."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq UnrealEditor.exe", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return "UnrealEditor.exe" in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def is_connected(self) -> bool:
        """Check if we have an active command connection to the editor."""
        return self._connected and self._command_socket is not None

    def connect(self, timeout: float = _DISCOVERY_TIMEOUT) -> None:
        """Discover the editor via UDP multicast and open a TCP command connection."""
        if self.is_connected():
            return
        self._remote_node_id = self._discover_editor(timeout)
        if not self._remote_node_id:
            raise EditorNotRunning("No editor instance found via multicast discovery")
        self._open_command_connection()

    def disconnect(self) -> None:
        """Close the command connection."""
        if self._command_socket:
            try:
                self._send_multicast(
                    _build_message("close_connection", self._node_id, self._remote_node_id)
                )
            except OSError:
                pass
            try:
                self._command_socket.close()
            except OSError:
                pass
            self._command_socket = None
        self._connected = False
        self._remote_node_id = None

    def run_command(self, command: str, exec_mode: str = "ExecuteFile", unattended: bool = True) -> dict:
        """Execute a Python command in the editor and return the result."""
        if not self.is_connected():
            try:
                self.connect()
            except Exception as e:
                raise EditorNotRunning(f"Cannot connect to editor: {e}") from e

        msg = _build_message("command", self._node_id, self._remote_node_id, {
            "command": command,
            "unattended": unattended,
            "exec_mode": exec_mode,
        })
        try:
            self._command_socket.sendall(msg.encode("utf-8"))
            data = self._recv_all(self._command_socket)
            parsed = _parse_message(data.decode("utf-8"))
            if parsed and parsed.get("type") == "command_result":
                return parsed.get("data", {"success": False, "result": "No data in response"})
            return {"success": False, "result": "Invalid response from editor"}
        except (OSError, ConnectionError) as e:
            self._connected = False
            self._command_socket = None
            raise EditorNotRunning(f"Lost connection to editor: {e}") from e

    def _discover_editor(self, timeout: float) -> str | None:
        """Send multicast pings and wait for a pong response."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            if hasattr(socket, "SO_REUSEPORT"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((UE_MULTICAST_BIND, UE_MULTICAST_PORT))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 0)
            sock.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                socket.inet_aton(UE_MULTICAST_BIND),
            )
            mcast_group = socket.inet_aton(UE_MULTICAST_GROUP) + socket.inet_aton(UE_MULTICAST_BIND)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mcast_group)
            sock.settimeout(1.0)

            ping_msg = _build_message("ping", self._node_id).encode("utf-8")
            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                sock.sendto(ping_msg, (UE_MULTICAST_GROUP, UE_MULTICAST_PORT))
                try:
                    data = sock.recv(_RECV_BUFFER)
                    msg = _parse_message(data.decode("utf-8"))
                    if msg and msg.get("type") == "pong" and msg.get("source") != self._node_id:
                        return msg["source"]
                except socket.timeout:
                    continue
        finally:
            sock.close()
        return None

    def _open_command_connection(self) -> None:
        """Open a TCP command connection."""
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen_sock.bind(("127.0.0.1", UE_EDITOR_PYTHON_PORT))
        listen_sock.listen(1)
        listen_sock.settimeout(5)
        try:
            for _ in range(6):
                self._send_multicast(
                    _build_message("open_connection", self._node_id, self._remote_node_id, {
                        "command_ip": "127.0.0.1",
                        "command_port": UE_EDITOR_PYTHON_PORT,
                    })
                )
                try:
                    self._command_socket, _ = listen_sock.accept()
                    self._command_socket.setblocking(True)
                    self._connected = True
                    return
                except socket.timeout:
                    continue
            raise EditorNotRunning("Editor did not connect to command channel")
        finally:
            listen_sock.close()

    def _send_multicast(self, msg_str: str) -> None:
        """Send a single message via UDP multicast."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 0)
            sock.sendto(msg_str.encode("utf-8"), (UE_MULTICAST_GROUP, UE_MULTICAST_PORT))
        finally:
            sock.close()

    @staticmethod
    def _recv_all(sock: socket.socket) -> bytes:
        """Receive all available data from a socket."""
        data = b""
        sock.settimeout(10)
        while True:
            try:
                part = sock.recv(_RECV_BUFFER)
                data += part
                if len(part) < _RECV_BUFFER:
                    break
            except socket.timeout:
                break
        return data
