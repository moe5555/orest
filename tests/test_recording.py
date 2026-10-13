"""A video played in place of the camera: its picture served as a camera's, its sound fed on."""

import time

import cv2
import numpy as np

from sitrep import devices, recording


class FakeSource:
    def __init__(self, value, name="Fake Camera"):
        self.device = devices.VideoDevice(0, name)
        self.frame = np.full((4, 4, 3), value, dtype=np.uint8)
        self.closed = False

    def latest(self):
        return self.frame

    def close(self):
        self.closed = True


def test_the_switch_serves_the_camera_until_a_playback_takes_its_place():
    camera, playback = FakeSource(1), FakeSource(2, "Aufnahme clip.mp4")
    switch = recording.Switch(camera)
    assert switch.latest()[0, 0, 0] == 1 and switch.playing is None
    switch.play(playback)
    assert switch.latest()[0, 0, 0] == 2
    assert switch.device.name == "Aufnahme clip.mp4"
    switch.play(None)
    assert switch.latest()[0, 0, 0] == 1
    assert playback.closed and not camera.closed


def test_closing_the_switch_closes_the_camera_and_the_playback():
    camera, playback = FakeSource(1), FakeSource(2)
    switch = recording.Switch(camera)
    switch.play(playback)
    switch.close()
    assert camera.closed and playback.closed


def write_clip(path, frames=10, fps=25):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (32, 24))
    for index in range(frames):
        writer.write(np.full((24, 32, 3), 10 * index, dtype=np.uint8))
    writer.release()


def test_a_video_without_sound_plays_its_picture_from_the_start(tmp_path):
    clip = tmp_path / "clip.avi"
    write_clip(clip)
    sound = []
    video = recording.Recording(clip, 16000)
    assert len(video.samples) == 0
    playback = video.play(sound.append)
    try:
        assert playback.latest().shape == (24, 32, 3)
        assert playback.name == "Aufnahme clip.avi" and playback.path == clip
        time.sleep(0.1)
        assert sound == []
    finally:
        playback.close()


def test_the_sound_is_fed_as_the_clock_passes_it():
    uhr = recording.Wiedergabe(0.0)
    fed = []
    with recording._Feeding(np.ones(1600, dtype=np.float32), 16000, uhr, fed.append):
        time.sleep(0.2)
    assert sum(len(chunk) for chunk in fed) == 1600
