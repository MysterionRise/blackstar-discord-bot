"""Capture from a virtual Linux audio device through real PortAudio and ALSA.

Opt-in, because it needs a sound server rather than mocks: PulseAudio with a
null sink called ``virtual_amp``, FFmpeg to play into it, and
``PULSE_SOURCE=virtual_amp.monitor`` so that ALSA's ``pulse`` device records
that sink. CI's ``linux-audio`` job sets this up; AGENTS.md shows how to run it
locally.
"""

import os
import shutil
import subprocess
import sys
import time

import numpy as np
import pytest
import sounddevice as sd

from guitar_amp_bot import device_finder
from guitar_amp_bot.audio_source import DeviceAudioSource
from guitar_amp_bot.device_finder import capture_problem, find_device_by_name, refresh_devices

pytestmark = [
    pytest.mark.linux_audio,
    pytest.mark.skipif(
        os.environ.get("LINUX_AUDIO_TEST") != "1" or not sys.platform.startswith("linux"),
        reason="needs the virtual Linux audio device; set LINUX_AUDIO_TEST=1",
    ),
]

SINK = os.environ.get("VIRTUAL_SINK", "virtual_amp")
DEVICE = "pulse"
# FFmpeg's 440 Hz test tone is about 2900 RMS; PulseAudio halves it when it
# downmixes the stereo sink to one channel.
TONE_RMS = 1000
SILENT_RMS = 50
# Generous: the first block after PortAudio is reinitialized can take seconds.
FRAME_TIMEOUT_SECONDS = 10.0
TONE_START_TIMEOUT_SECONDS = 10.0


def _sink_inputs() -> str:
    return subprocess.run(
        ["pactl", "list", "short", "sink-inputs"], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture(scope="module", autouse=True)
def left_only_tone():
    """Play a tone on the left channel only, silence on the right, into the sink."""
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "FFmpeg is needed to play the test tone"
    before = _sink_inputs()
    player = subprocess.Popen(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-filter_complex",
            "[0:a][1:a]amerge=inputs=2[out]",
            "-map",
            "[out]",
            "-f",
            "pulse",
            "-device",
            SINK,
            "left-only-tone",
        ]
    )
    # Wait for the tone itself rather than for a fixed time: FFmpeg registers
    # with the sound server a moment before its audio reaches the monitor.
    deadline = time.monotonic() + TONE_START_TIMEOUT_SECONDS
    while _sink_inputs() == before:
        assert player.poll() is None, "FFmpeg exited before playing the tone"
        assert time.monotonic() < deadline, "the tone never reached the sound server"
        time.sleep(0.1)
    _wait_until_audible(deadline)
    yield
    player.terminate()
    player.wait(timeout=10)


def _wait_until_audible(deadline: float) -> None:
    """Read the monitor directly, bypassing the code under test, until the tone shows."""
    refresh_devices()
    device = find_device_by_name(DEVICE)
    assert device is not None
    with sd.RawInputStream(device=device.index, channels=2, samplerate=48000, dtype="int16") as mic:
        while time.monotonic() < deadline:
            data, _overflowed = mic.read(960)
            block = np.frombuffer(data, dtype=np.int16).reshape(-1, 2)
            if _rms(block[:, 0]) > TONE_RMS:
                return
    pytest.fail("the tone never became audible on the monitor source")


def _capture(input_channels: tuple[int, ...], blocks: int = 10) -> np.ndarray:
    """Return *blocks* 20 ms blocks captured the way /stream captures them."""
    refresh_devices()
    device = find_device_by_name(DEVICE, input_channels)
    assert device is not None
    source = DeviceAudioSource(device, device_query=DEVICE, input_channels=input_channels)
    source.start()
    try:
        # The first blocks can predate the tone reaching the monitor source.
        captured = [source._buffer.get(timeout=FRAME_TIMEOUT_SECONDS) for _ in range(blocks + 5)]
        assert source.state == "running"
    finally:
        source.cleanup()
    assert device_finder._open_streams == 0
    return np.frombuffer(b"".join(captured[5:]), dtype=np.int16).reshape(-1, 2)


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt((samples.astype(float) ** 2).mean()))


def test_the_pulse_input_is_listed_under_alsa_and_can_capture():
    refresh_devices()
    device = find_device_by_name(DEVICE)

    assert device is not None
    assert device.hostapi == "ALSA"
    assert capture_problem(device) is None
    assert capture_problem(device, (1,)) is None


def test_stereo_capture_keeps_left_and_right_apart():
    stereo = _capture((1, 2))

    assert _rms(stereo[:, 0]) > TONE_RMS
    assert _rms(stereo[:, 1]) < SILENT_RMS


def test_a_reversed_pair_swaps_the_sides():
    stereo = _capture((2, 1))

    assert _rms(stereo[:, 0]) < SILENT_RMS
    assert _rms(stereo[:, 1]) > TONE_RMS


def test_a_mono_input_reaches_both_sides():
    stereo = _capture((1,))

    assert np.array_equal(stereo[:, 0], stereo[:, 1])
    assert _rms(stereo[:, 0]) > TONE_RMS / 2
