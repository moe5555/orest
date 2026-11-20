"""The new-body pulse to Max: one rising edge per body, always ending at 0.

Needs no camera, pose model or Max.
"""

import threading
import time

import pytest
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from action import tracking
from osc import Sender
from sitrep import pulse

from test_action import detections, figure


class RecordingSender:
    def __init__(self):
        self.sent = []
        self.at = []
        self.host, self.port = "192.168.10.3", 7400

    def send(self, message):
        self.sent.append(message)
        self.at.append(time.perf_counter())


def values(sender, address=pulse.NEW_BODY):
    return [arguments[0] for sent, arguments in sender.sent if sent == address]


def settle(seconds=0.2):
    time.sleep(seconds)


def test_a_new_body_sends_1_then_0():
    sender = RecordingSender()
    pulse.Pulse(sender, width=0.02).fire(1)
    assert values(sender) == [1]
    settle()
    assert values(sender) == [1, 0, 0]


def test_a_second_body_while_high_is_its_own_rising_edge():
    sender = RecordingSender()
    beat = pulse.Pulse(sender, width=0.05)
    beat.fire(1)
    beat.fire(2)
    settle()
    assert values(sender) == [1, 0, 1, 0, 0]
    assert beat.fired == 2


def test_closing_while_high_leaves_max_at_0():
    sender = RecordingSender()
    beat = pulse.Pulse(sender, width=10.0)
    beat.fire(1)
    beat.close()
    assert values(sender) == [1, 0, 0]
    settle(0.05)
    assert values(sender) == [1, 0, 0]


def test_closing_while_low_sends_nothing():
    sender = RecordingSender()
    pulse.Pulse(sender).close()
    assert sender.sent == []


def test_a_muted_pulse_sends_nothing():
    sender = RecordingSender()
    beat = pulse.Pulse(sender)
    beat.muted = True
    beat.fire(1)
    assert sender.sent == []


def test_the_stroboscope_opening_and_closing_sends_zeichen():
    sender = RecordingSender()
    strobe = pulse.Strobe(sender)
    strobe.show(True)
    strobe.show(True)
    assert values(sender, pulse.ZEICHEN) == [1]
    strobe.show(False)
    assert values(sender, pulse.ZEICHEN) == [1, 0, 0]


def test_no_fackel_while_the_stroboscope_is_closed():
    sender = RecordingSender()
    assert not pulse.Strobe(sender).cycle([(0, 50)])
    settle(0.1)
    assert sender.sent == []


def test_fackel_is_lit_with_each_flash_of_the_cycle():
    sender = RecordingSender()
    strobe = pulse.Strobe(sender)
    strobe.show(True)
    began = time.perf_counter()
    assert strobe.cycle([(0, 40), (130, 30)])
    settle(0.3)
    fackel = [(arguments[0], at - began) for (address, arguments), at
              in zip(sender.sent, sender.at) if address == pulse.FACKEL]
    assert [value for value, _ in fackel] == [1, 0, 0, 1, 0, 0]
    rises = [at for value, at in fackel if value == 1]
    falls = [at for (value, at), (before, _) in zip(fackel[1:], fackel) if value == 0 and before == 1]
    assert rises[0] == pytest.approx(0.0, abs=0.01)
    assert rises[1] == pytest.approx(0.130, abs=0.01)
    assert falls[0] - rises[0] == pytest.approx(0.040, abs=0.01)
    assert falls[1] - rises[1] == pytest.approx(0.030, abs=0.01)


def test_closing_the_stroboscope_mid_flash_leaves_fackel_at_0():
    sender = RecordingSender()
    strobe = pulse.Strobe(sender)
    strobe.show(True)
    strobe.cycle([(0, 200), (300, 50)])
    settle(0.05)
    strobe.show(False)
    settle(0.4)
    assert values(sender, pulse.FACKEL) == [1, 0, 0]


def test_cut_to_black_ends_fackel_and_keeps_zeichen():
    sender = RecordingSender()
    strobe = pulse.Strobe(sender)
    strobe.show(True)
    strobe.cycle([(0, 200), (300, 50)])
    settle(0.05)
    strobe.black(True)
    assert not strobe.cycle([(0, 50)])
    settle(0.4)
    assert values(sender, pulse.FACKEL) == [1, 0, 0]
    assert values(sender, pulse.ZEICHEN) == [1]
    strobe.show(False)
    strobe.show(True)
    assert strobe.cycle([(0, 10)])


def test_the_tracker_reports_each_new_body_once():
    new = []
    tracker = tracking.BodyTracker(on_new=new.append)
    tracker.update(*detections(figure(500)), at=0.0)
    tracker.update(*detections(figure(505)), at=0.04)
    tracker.update(*detections(figure(510), figure(1500)), at=0.08)
    assert new == [1, 2]


def test_a_single_frame_detection_is_reported():
    new = []
    tracker = tracking.BodyTracker(on_new=new.append)
    tracker.update(*detections(figure(500)), at=0.0)
    tracker.update(*detections(), at=0.04)
    assert new == [1]


def test_a_body_lost_past_the_forget_window_is_reported_again():
    new = []
    tracker = tracking.BodyTracker(on_new=new.append)
    tracker.update(*detections(figure(500)), at=0.0)
    tracker.update(*detections(figure(500)), at=tracking.FORGET + 0.5)
    assert new == [1, 2]


@pytest.fixture
def receiver():
    """A loopback OSC server that collects three messages."""
    received = []
    dispatcher = Dispatcher()
    dispatcher.map(pulse.NEW_BODY, lambda address, *arguments: received.append(arguments[0]))
    server = BlockingOSCUDPServer(("127.0.0.1", 0), dispatcher)
    server.timeout = 2.0

    def serve():
        for _ in range(3):
            server.handle_request()

    thread = threading.Thread(target=serve)
    thread.start()
    yield server.server_address[1], received, thread
    server.server_close()


def test_the_pulse_arrives_over_udp(receiver):
    port, received, thread = receiver
    pulse.Pulse(Sender("127.0.0.1", port), width=0.02).fire(1)
    thread.join(timeout=3.0)
    assert received == [1, 0, 0]
