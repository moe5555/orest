"""The OSC wire between Apollon and TouchDesigner.

knowledge/components/03_render.md gives the interface two channels: "OSC
carries messages, not pixels." This package is that channel, shared by
everything that speaks on it — search results from `smartsearch`, live reports
and the presence roster from `sitrep`, and the localhost interface when it
arrives.

There is one TouchDesigner and one OSC In DAT, so there is one definition of
where to reach it. Addresses are namespaced by what sends them
(`/apollon/results/`, `/apollon/sitrep/`, `/apollon/presence/`), which lets a single
receiver in TouchDesigner route on the prefix.

Every location is overridable by environment variable: the machine that runs
this in the Probebuehne is not the machine it was written on.
"""

import os

from pythonosc.udp_client import SimpleUDPClient

# Where TouchDesigner listens: its OSC In DAT.
TD_HOST = os.environ.get("APOLLON_TD_HOST", "127.0.0.1")
TD_PORT = int(os.environ.get("APOLLON_TD_PORT", "10000"))

# Where Apollon listens for OSC from TouchDesigner or QLab, such as the start and
# stop of a live body capture. The return channel beside TD_PORT.
CONTROL_HOST = os.environ.get("APOLLON_CONTROL_HOST", "127.0.0.1")
CONTROL_PORT = int(os.environ.get("APOLLON_CONTROL_PORT", "10001"))

# An address and its positional arguments, ready to send.
Message = tuple[str, list]


class Sender:
    """Sends messages to one OSC receiver over UDP."""

    def __init__(self, host: str = TD_HOST, port: int = TD_PORT):
        self.host = host
        self.port = port
        self._client = SimpleUDPClient(host, port)

    def send(self, message: Message):
        address, arguments = message
        self._client.send_message(address, arguments)

    def send_all(self, messages):
        """Send messages in order, which is how a receiver reads them as rows."""
        for message in messages:
            self.send(message)
