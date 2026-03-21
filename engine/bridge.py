"""SCBridge — OSC communication layer between Python and scsynth."""

import logging
import subprocess
import time
from pathlib import Path

from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_bundle_builder import OscBundleBuilder, IMMEDIATELY
from pythonosc.osc_message_builder import OscMessageBuilder

log = logging.getLogger(__name__)

# scsynth add actions
ADD_TO_HEAD = 0
ADD_TO_TAIL = 1
ADD_BEFORE = 2
ADD_AFTER = 3


class SCBridge:
    """Thin wrapper around scsynth OSC protocol.

    Manages node/bus ID allocation and provides ergonomic methods
    for synth creation, parameter control, and group management.
    """

    def __init__(self, host="127.0.0.1", port=57110):
        self.host = host
        self.port = port
        self.client = SimpleUDPClient(host, port)
        self.next_node_id = 2000
        self.next_bus_id = 16  # buses 0-15 reserved for hardware I/O
        self._freed_buses: list[tuple[int, int]] = []  # (bus_id, channels)

    # -- Node ID allocation --------------------------------------------------

    def _alloc_node_id(self) -> int:
        node_id = self.next_node_id
        self.next_node_id += 1
        return node_id

    # -- Bus allocation -------------------------------------------------------

    def alloc_bus(self, channels: int = 1) -> int:
        """Allocate a private audio bus. Returns the bus index."""
        # Try to reuse a freed bus of the right size
        for i, (bus_id, ch) in enumerate(self._freed_buses):
            if ch == channels:
                self._freed_buses.pop(i)
                return bus_id
        bus_id = self.next_bus_id
        self.next_bus_id += channels
        return bus_id

    def free_bus(self, bus_id: int, channels: int = 1):
        """Return a bus to the pool for reuse."""
        self._freed_buses.append((bus_id, channels))

    # -- Synth creation -------------------------------------------------------

    def synth(
        self,
        name: str,
        target_group: int | None = None,
        add_action: int = ADD_TO_HEAD,
        **params,
    ) -> int:
        """Create a synth node. Returns the allocated node ID.

        Params are sent as key-value pairs. Values are coerced to float.
        """
        node_id = self._alloc_node_id()
        target = target_group if target_group is not None else 1
        args: list = []
        for k, v in params.items():
            args.extend([k, float(v)])
        self.client.send_message(
            "/s_new", [name, node_id, add_action, target] + args
        )
        return node_id

    # -- Node control ---------------------------------------------------------

    def set(self, node_id: int, **params):
        """Set parameters on a running synth or group."""
        args: list = [node_id]
        for k, v in params.items():
            args.extend([k, float(v)])
        self.client.send_message("/n_set", args)

    def free(self, node_id: int):
        """Free a node (synth or group). Freeing a group frees all children."""
        self.client.send_message("/n_free", [node_id])

    # -- Groups ---------------------------------------------------------------

    def new_group(self, target: int = 1, add_action: int = ADD_TO_TAIL) -> int:
        """Create a new group node. Returns the group ID."""
        group_id = self._alloc_node_id()
        self.client.send_message("/g_new", [group_id, add_action, target])
        return group_id

    # -- Bundled messages (sample-accurate timing) ----------------------------

    def send_bundle(self, bundle: OscBundleBuilder):
        """Send a pre-built OSC bundle."""
        self.client.send(bundle.build())

    def make_synth_msg(
        self,
        name: str,
        target_group: int | None = None,
        add_action: int = ADD_TO_HEAD,
        **params,
    ) -> tuple[int, OscMessageBuilder]:
        """Build an /s_new message without sending it. Returns (node_id, msg).

        Use this to construct bundles for sample-accurate note sequences.
        """
        node_id = self._alloc_node_id()
        target = target_group if target_group is not None else 1
        msg = OscMessageBuilder(address="/s_new")
        msg.add_arg(name)
        msg.add_arg(node_id)
        msg.add_arg(add_action)
        msg.add_arg(target)
        for k, v in params.items():
            msg.add_arg(k)
            msg.add_arg(float(v))
        return node_id, msg

    # -- SynthDef loading -----------------------------------------------------

    def load_synthdef(self, path: str | Path):
        """Load a compiled .scsyndef file into the server."""
        self.client.send_message("/d_load", [str(path)])

    def load_synthdef_dir(self, directory: str | Path):
        """Load all .scsyndef files in a directory."""
        self.client.send_message("/d_loadDir", [str(directory)])

    # -- Server management ----------------------------------------------------

    def notify(self, on: bool = True):
        """Register/unregister for server notifications."""
        self.client.send_message("/notify", [int(on)])

    def status(self):
        """Request server status (response comes async via /status.reply)."""
        self.client.send_message("/status", [])

    def dump_tree(self, group: int = 0, controls: bool = False):
        """Print the server's node tree to scsynth's stdout."""
        self.client.send_message("/g_dumpTree", [group, int(controls)])

    def free_all(self):
        """Free all nodes in the default group. Use for panic/reset."""
        self.client.send_message("/g_freeAll", [1])

    def quit(self):
        """Shut down scsynth."""
        self.client.send_message("/quit", [])


def boot_scsynth(
    port: int = 57110,
    sample_rate: int = 48000,
    block_size: int = 64,
    num_buffers: int = 1024,
    num_audio_buses: int = 1024,
    num_control_buses: int = 4096,
    max_nodes: int = 4096,
    max_synthdefs: int = 1024,
    mem_size: int = 65536,  # RT memory in KB (default 8192 = 8MB)
) -> subprocess.Popen:
    """Boot scsynth as a subprocess. Returns the Popen handle."""
    cmd = [
        "scsynth",
        "-u", str(port),
        "-a", str(num_audio_buses),
        "-c", str(num_control_buses),
        "-n", str(max_nodes),
        "-d", str(max_synthdefs),
        "-b", str(num_buffers),
        "-m", str(mem_size),
        "-R", "0",  # no rendezvous (Bonjour)
        "-S", str(sample_rate),
        "-Z", str(block_size),
    ]
    log.info("Booting scsynth: %s", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(1)  # give scsynth a moment to bind the port
    return proc
