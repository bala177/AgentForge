"""
nodes/protocol.py — Communication protocol for remote device nodes.

Defines the message format for Gateway ↔ Node communication over WebSocket.

Protocol:
  Node → Gateway:
    {"type": "register", "node_id": "...", "platform": "...", "capabilities": [...]}
    {"type": "heartbeat", "node_id": "..."}
    {"type": "result", "task_id": "...", "data": "...", "status": "ok"|"error"}

  Gateway → Node:
    {"type": "task", "task_id": "...", "action": "...", "params": {...}}
    {"type": "ack", "task_id": "...", "status": "received"}
    {"type": "ping"}

Phase 4 implementation — defines message types and validation.
"""

import uuid
import time
from dataclasses import dataclass, field
from enum import Enum
from log_config import get_logger

log = get_logger("protocol")


class MessageType(str, Enum):
    # Node → Gateway
    REGISTER = "register"
    HEARTBEAT = "heartbeat"
    RESULT = "result"
    CAPABILITY_UPDATE = "capability_update"

    # Gateway → Node
    TASK = "task"
    ACK = "ack"
    PING = "ping"
    CANCEL = "cancel"


@dataclass
class NodeTask:
    """A task sent from the gateway to a remote node."""
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:10]}")
    action: str = ""                       # e.g. "take_screenshot", "run_shell", "read_clipboard"
    params: dict = field(default_factory=dict)
    node_id: str = ""
    created_at: float = field(default_factory=time.time)
    timeout: float = 30.0                  # seconds
    status: str = "pending"                # "pending" | "sent" | "completed" | "failed" | "timeout"
    result: str = ""

    def to_message(self) -> dict:
        """Format as a WebSocket message to send to the node."""
        return {
            "type": MessageType.TASK.value,
            "task_id": self.task_id,
            "action": self.action,
            "params": self.params,
            "timeout": self.timeout,
        }

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.timeout

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "action": self.action,
            "params": self.params,
            "node_id": self.node_id,
            "created_at": self.created_at,
            "timeout": self.timeout,
            "status": self.status,
            "result": self.result,
        }


def validate_message(data: dict) -> tuple[bool, str]:
    """
    Validate an incoming WebSocket message from a node.
    Returns (is_valid, error_message).
    """
    if not isinstance(data, dict):
        return False, "Message must be a JSON object"

    msg_type = data.get("type", "")
    if not msg_type:
        return False, "Missing 'type' field"

    if msg_type == MessageType.REGISTER.value:
        if not data.get("node_id"):
            return False, "Register message missing 'node_id'"
        if not data.get("platform"):
            return False, "Register message missing 'platform'"
        return True, ""

    if msg_type == MessageType.HEARTBEAT.value:
        if not data.get("node_id"):
            return False, "Heartbeat message missing 'node_id'"
        return True, ""

    if msg_type == MessageType.RESULT.value:
        if not data.get("task_id"):
            return False, "Result message missing 'task_id'"
        if "status" not in data:
            return False, "Result message missing 'status'"
        return True, ""

    if msg_type == MessageType.CAPABILITY_UPDATE.value:
        if not data.get("node_id"):
            return False, "Capability update missing 'node_id'"
        return True, ""

    return False, f"Unknown message type: {msg_type}"
