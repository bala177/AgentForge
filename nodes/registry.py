"""
nodes/registry.py — Remote device node registry.

Tracks connected device nodes (iOS, Android, Mac, etc.) and their
capabilities. Nodes connect via WebSocket and register their tools.

Phase 4 implementation — currently a functional stub that can
register nodes and track their status.
"""

import time
import threading
from dataclasses import dataclass, field
from log_config import get_logger

log = get_logger("nodes")


@dataclass
class NodeInfo:
    """Represents a connected remote device node."""
    node_id: str
    platform: str                          # "ios" | "android" | "macos" | "linux" | "windows"
    capabilities: list[str] = field(default_factory=list)  # e.g. ["camera", "shell", "clipboard"]
    hostname: str = ""
    ip_address: str = ""
    connected_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)
    status: str = "online"                 # "online" | "busy" | "offline"

    def heartbeat(self):
        self.last_heartbeat = time.time()

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_heartbeat

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "platform": self.platform,
            "capabilities": self.capabilities,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "connected_at": self.connected_at,
            "last_heartbeat": self.last_heartbeat,
            "idle_seconds": round(self.idle_seconds, 1),
            "status": self.status,
            "metadata": self.metadata,
        }


class NodeRegistry:
    """
    Track connected device nodes and their capabilities.

    Thread-safe registry with heartbeat-based liveness detection.
    """

    def __init__(self, stale_timeout: int = 60):
        self._nodes: dict[str, NodeInfo] = {}
        self._lock = threading.Lock()
        self.stale_timeout = stale_timeout
        log.info("NodeRegistry init  stale_timeout=%ds", stale_timeout)

    def register(
        self,
        node_id: str,
        platform: str,
        capabilities: list[str] | None = None,
        hostname: str = "",
        ip_address: str = "",
        metadata: dict | None = None,
    ) -> NodeInfo:
        """Register a new node or update an existing one."""
        with self._lock:
            if node_id in self._nodes:
                node = self._nodes[node_id]
                node.platform = platform
                node.capabilities = capabilities or node.capabilities
                node.hostname = hostname or node.hostname
                node.ip_address = ip_address or node.ip_address
                node.metadata.update(metadata or {})
                node.heartbeat()
                node.status = "online"
                log.info("Node re-registered: %s (%s)", node_id, platform)
            else:
                node = NodeInfo(
                    node_id=node_id,
                    platform=platform,
                    capabilities=capabilities or [],
                    hostname=hostname,
                    ip_address=ip_address,
                    metadata=metadata or {},
                )
                self._nodes[node_id] = node
                log.info("Node registered: %s (%s) capabilities=%s",
                         node_id, platform, capabilities)
        return node

    def heartbeat(self, node_id: str) -> bool:
        """Update heartbeat timestamp. Returns False if node not found."""
        with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.heartbeat()
                return True
        return False

    def get_node(self, node_id: str) -> NodeInfo | None:
        """Get a node by ID."""
        with self._lock:
            return self._nodes.get(node_id)

    def get_capable_nodes(self, capability: str) -> list[NodeInfo]:
        """Find all online nodes that have a given capability."""
        with self._lock:
            return [
                n for n in self._nodes.values()
                if capability in n.capabilities
                and n.status == "online"
                and n.idle_seconds < self.stale_timeout
            ]

    def unregister(self, node_id: str) -> bool:
        """Remove a node from the registry."""
        with self._lock:
            if node_id in self._nodes:
                del self._nodes[node_id]
                log.info("Node unregistered: %s", node_id)
                return True
        return False

    def remove_stale(self) -> int:
        """Remove nodes that haven't sent a heartbeat recently."""
        now = time.time()
        with self._lock:
            stale = [
                nid for nid, n in self._nodes.items()
                if (now - n.last_heartbeat) > self.stale_timeout
            ]
            for nid in stale:
                self._nodes[nid].status = "offline"
                del self._nodes[nid]
            if stale:
                log.info("Removed %d stale node(s): %s", len(stale), stale)
        return len(stale)

    def list_nodes(self) -> list[dict]:
        """Return summary of all registered nodes."""
        with self._lock:
            return [n.to_dict() for n in self._nodes.values()]

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._nodes)
