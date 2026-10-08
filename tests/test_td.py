"""The OSC messages that announce search results to TouchDesigner."""

import threading
from pathlib import Path

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from smartsearch import main, td
from smartsearch.client import Hit
from smartsearch.clips import Clip

HIT = Hit(
    media_id="3", filename="Theaterprobe.mp4", ts=1008.0, te=1016.0, score=1.94,
    target="video", vector_id="0/3/2016", media_url="http://127.0.0.1:9670/p/media/3",
    thumbnail_url="",
)


def test_a_hit_message_carries_rank_clip_range_score_source_and_preroll():
    address, arguments = td.hit_message("q1", 2, Clip(Path("clips/a.mp4"), 0.458), HIT)
    assert address == td.HIT
    query_id, rank, clip, ts, te, score, source, preroll = arguments
    assert (query_id, rank, ts, te, score, source, preroll) ==         ("q1", 2, 1008.0, 1016.0, 1.94, "Theaterprobe.mp4", 0.458)
    assert clip.endswith("clips/a.mp4")


def test_clip_paths_are_absolute_with_forward_slashes():
    _, arguments = td.hit_message("q1", 1, Clip(Path("clips") / "a.mp4", 0.0), HIT)
    assert "\\" not in arguments[2]
    assert Path(arguments[2]).is_absolute()


def test_begin_announces_how_many_hits_follow():
    assert td.begin_message("q1", 20) == (td.BEGIN, ["q1", 20])


def test_query_ids_differ_between_searches():
    assert td.new_query_id() != td.new_query_id()


def test_delivery_frames_the_hits_with_begin_and_end_in_rank_order(tmp_path, monkeypatch):
    sent = []

    class FakeSender:
        def send(self, message):
            sent.append(message)

    monkeypatch.setattr(main.td, "Sender", FakeSender)
    monkeypatch.setattr(main.config, "clips_dir", lambda project: tmp_path)
    monkeypatch.setattr(main.clips, "cut_all",
                        lambda hits, *a: ((r, h, Clip(tmp_path / f"{r}.mp4", 0.0))
                                          for r, h in enumerate(hits, 1)))

    main.deliver([HIT, HIT], "p", "fast", "libx264", send_td=True)

    assert [address for address, _ in sent] == [td.BEGIN, td.HIT, td.HIT, td.END]
    assert [arguments[1] for address, arguments in sent if address == td.HIT] == [1, 2]
    assert len({arguments[0] for _, arguments in sent}) == 1


def test_delivery_trims_the_clips_but_keeps_the_ones_just_sent(tmp_path, monkeypatch):
    pruned = {}
    monkeypatch.setattr(main.config, "clips_dir", lambda project: tmp_path)
    monkeypatch.setattr(main.config, "CLIPS_MAX_GB", 2.0)
    monkeypatch.setattr(main.clips, "cut_all",
                        lambda hits, *a: ((r, h, Clip(tmp_path / f"{r}.mp4", 0.0))
                                          for r, h in enumerate(hits, 1)))
    monkeypatch.setattr(main.clips, "prune",
                        lambda directory, max_bytes, keep: pruned.update(
                            directory=directory, max_bytes=max_bytes, keep=list(keep)) or 0)

    main.deliver([HIT, HIT], "p", "precise", "libx264", send_td=False)

    assert pruned == {"directory": tmp_path, "max_bytes": 2_000_000_000,
                      "keep": [tmp_path / "1.mp4", tmp_path / "2.mp4"]}


def test_messages_arrive_over_udp_as_sent():
    received = []
    dispatcher = Dispatcher()
    dispatcher.map("/apollon/*", lambda address, *arguments: received.append((address, list(arguments))))
    server = BlockingOSCUDPServer(("127.0.0.1", 0), dispatcher)
    port = server.server_address[1]
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    td.Sender("127.0.0.1", port).send(td.hit_message("q1", 1, Clip(Path("a.mp4"), 3.0), HIT))
    thread.join(timeout=5)
    server.server_close()

    address, arguments = received[0]
    assert address == td.HIT
    assert arguments[:2] == ["q1", 1]
    assert arguments[3] == 1008.0 and arguments[6] == "Theaterprobe.mp4"
    assert arguments[7] == 3.0
