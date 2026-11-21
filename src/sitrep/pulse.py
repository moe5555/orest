"""Pulses to Max over OSC for events on stage: 1, then 0 after WIDTH seconds;
and the number of bodies tracked.

    /apollon/tracking/new         the body tracker starts following someone
    /apollon/tracking/podestOff   a tracked body steps off the Podest
    /apollon/tracking/podestOn    a tracked body steps onto the Podest

New bodies (action/tracking.py) are not filtered, so a detection seen for a
single frame pulses too, as does a person the tracker lost for longer than
tracking.FORGET and picked up again. The operator switches them off and on
with N in every scene (scenes.NEW_BODY_KEY); each scene starts with them on.

The Podest pulses come in a scene with a Podest rule, which in scenes.toml is
Szene 1, for every body tracked, named or not (podest.Stance); Risiko is still
counted for the people the scene rates alone. A body is on the Podest in any
posture, standing, kneeling or sitting on it. A body the tracker briefly lost
and finds with the other stance has taken a step; one re-found as a new body
(tracking.FORGET) has not. A step is sent from the frame that completes it,
podest.HALTEN frames (0.16 s) after the feet cross.

In a scene with `body_count` (scenes.Scene), which in scenes.toml is Szene 1,
Max is also sent the number of bodies the tracker follows (Count), not as a
pulse but as a value, each time it changes:

    /apollon/tracking/bodyCount   e.g. 4 while four bodies are tracked

A body counts from the frame the tracker starts following it, as for
/apollon/tracking/new, until it has gone undetected for tracking.FORGET (3 s).
The current number is also sent each time the count resumes, as such a scene
is entered from another and as its stroboscope closes, so Max holds it from
then on whatever it held before.

While a scene's stroboscope is open (key T, scenes.Current.strobe), these
four are muted and the stroboscope is signalled instead (Strobe):

    /apollon/strobe/zeichen   1 as the stroboscope opens, 0 as it closes
    /apollon/strobe/fackel    1 while each flash of fire is lit, 0 between:
                              two pulses a cycle, as long as the flashes

An event that arrives while its pulse is still high drops it to 0 and raises
it again at once, so each event is its own rising edge. The 0 that ends a
pulse is sent twice: OSC travels over UDP without delivery, and a single lost
0 would leave Max reading 1 until the next event.

In Max:

    [udpreceive 7400]
    -> [route /apollon/tracking/new /apollon/tracking/podestOff /apollon/tracking/podestOn
              /apollon/strobe/zeichen /apollon/strobe/fackel /apollon/tracking/bodyCount]
    -> [sel 1] on each outlet but bodyCount's, which carries the number

Host and port are osc.PULSE_HOST and osc.PULSE_PORT.
"""

import threading
import time

from osc import PULSE_HOST, PULSE_PORT, Sender

NEW_BODY = "/apollon/tracking/new"
PODEST_OFF = "/apollon/tracking/podestOff"
PODEST_ON = "/apollon/tracking/podestOn"
ZEICHEN = "/apollon/strobe/zeichen"
FACKEL = "/apollon/strobe/fackel"
BODY_COUNT = "/apollon/tracking/bodyCount"

# Seconds the pulse stays at 1. Long enough for Max's scheduler to see the 1
# before the 0, short enough that people entering together still give one edge
# each.
WIDTH = 0.1


class Pulse:
    """Raises a short 1 on `address` for each call to `fire`.

    `fire` is called on the thread that sees the event and returns at once;
    the 0 follows from a timer thread.
    """

    def __init__(self, sender: Sender | None = None, *, address: str = NEW_BODY,
                 width: float = WIDTH):
        self.sender = sender or Sender(PULSE_HOST, PULSE_PORT)
        self.address = address
        self._width = width
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self.fired = 0
        # A muted pulse ignores `fire`; one already high still ends.
        self.muted = False

    def fire(self, about=None):
        """Raise the pulse. `about` names what fired it, a body id or a
        person, and is not sent."""
        with self._lock:
            if self.muted:
                return
            if self._timer is not None:
                self._timer.cancel()
                self.sender.send((self.address, [0]))
            self.sender.send((self.address, [1]))
            self.fired += 1
            self._timer = threading.Timer(self._width, self._lower)
            self._timer.daemon = True
            self._timer.start()

    def _lower(self):
        with self._lock:
            if self._timer is not threading.current_thread():
                return
            self._timer = None
            self._send_low()

    def _send_low(self):
        self.sender.send((self.address, [0]))
        self.sender.send((self.address, [0]))

    def close(self):
        """Stop, leaving Max at 0."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
                self._send_low()


class Count:
    """Sends the number of bodies tracked each time it changes, while not muted.

    `update` is called on the thread that tracks the bodies, `muted` set from
    the scene's; unmuting sends the number at once.
    """

    def __init__(self, sender: Sender, *, address: str = BODY_COUNT):
        self.sender = sender
        self.address = address
        self._lock = threading.Lock()
        self._count = 0
        self._muted = True

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, muted: bool):
        with self._lock:
            if muted == self._muted:
                return
            self._muted = muted
            if not muted:
                self.sender.send((self.address, [self._count]))

    def update(self, count: int):
        """The tracker now follows `count` bodies."""
        with self._lock:
            if count == self._count:
                return
            self._count = count
            if not self._muted:
                self.sender.send((self.address, [count]))


class Strobe:
    """zeichen and fackel for a scene's stroboscope.

    The page draws the stroboscope and chooses each cycle's flash lengths
    (sitrep.js, `strobe`), and announces them as the cycle begins; `cycle`
    sends fackel on that schedule. The flashes last 30-60 ms, so the schedule
    sleeps with time.sleep, which keeps to the millisecond on Windows, where a
    timer or an event wait rounds to the 15.6 ms system tick. Cut to black
    (`black`), it sends no fackel while zeichen stays 1.
    """

    def __init__(self, sender: Sender):
        self.sender = sender
        self.on = False
        self.dark = False
        self._lock = threading.Lock()
        # Set to end the cycle being sent.
        self._stop: threading.Event | None = None

    def show(self, on: bool):
        """The stroboscope opened (True) or closed: zeichen 1, or zeichen 0
        with any flash being sent cut short."""
        with self._lock:
            if on == self.on:
                return
            self.on = on
            self.dark = False
            self._end_cycle()
            if on:
                self.sender.send((ZEICHEN, [1]))
            else:
                self.sender.send((ZEICHEN, [0]))
                self.sender.send((ZEICHEN, [0]))

    def cycle(self, flashes: list[tuple[float, float]]) -> bool:
        """Send fackel for one cycle's flashes, each as its start and length in
        ms from now. False while the stroboscope is closed or cut to black."""
        with self._lock:
            if not self.on or self.dark:
                return False
            self._end_cycle()
            stop = self._stop = threading.Event()
        threading.Thread(target=self._send_cycle, args=(sorted(flashes), stop),
                         daemon=True).start()
        return True

    def black(self, dark: bool):
        """Cut the open stroboscope to black (True), any flash being sent cut
        short, or let it flash again."""
        with self._lock:
            self.dark = dark and self.on
            if self.dark:
                self._end_cycle()

    def _end_cycle(self):
        if self._stop is not None:
            self._stop.set()
            self._stop = None

    def _send_cycle(self, flashes, stop: threading.Event):
        began = time.perf_counter()
        high = False
        for start, length in flashes:
            for at, value in ((start, 1), (start + length, 0)):
                time.sleep(max(0.0, began + at / 1000 - time.perf_counter()))
                if stop.is_set():
                    break
                self.sender.send((FACKEL, [value]))
                if value == 0:
                    self.sender.send((FACKEL, [0]))
                high = value == 1
            if stop.is_set():
                break
        if high:
            self.sender.send((FACKEL, [0]))
            self.sender.send((FACKEL, [0]))
