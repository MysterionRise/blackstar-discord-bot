"""Tests for guitar_amp_bot.device_finder."""

import logging
from unittest.mock import patch

import pytest

from guitar_amp_bot import device_finder
from guitar_amp_bot.device_finder import (
    AmbiguousDeviceError,
    AudioDevice,
    capture_problem,
    find_device_by_name,
    format_input_channels,
    list_input_devices,
    live_device_name,
    match_devices,
    note_stream_closed,
    note_stream_opened,
    parse_input_channels,
    refresh_devices,
    refresh_devices_if_idle,
    select_device,
)

FAKE_DEVICES = [
    {"name": "Built-in Microphone", "max_input_channels": 1, "default_samplerate": 44100.0},
    {"name": "Blackstar ID:Core V4", "max_input_channels": 2, "default_samplerate": 48000.0},
    {"name": "HDMI Output", "max_input_channels": 0, "default_samplerate": 48000.0},
]


@pytest.fixture(autouse=True)
def capture_supported(monkeypatch):
    """PortAudio accepts 48 kHz stereo on every device unless a test says otherwise."""
    monkeypatch.setattr(device_finder.sd, "check_input_settings", lambda **_kwargs: None)


def _device(index, name, hostapi="", *, channels=2, rate=48000.0):
    return AudioDevice(
        index=index,
        name=name,
        max_input_channels=channels,
        default_samplerate=rate,
        hostapi=hostapi,
    )


@patch("guitar_amp_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES)
def test_list_input_devices_filters_outputs(_mock):
    """Only devices with input channels should be returned."""
    devices = list_input_devices()
    assert len(devices) == 2
    assert all(d.max_input_channels > 0 for d in devices)


@patch("guitar_amp_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES)
def test_find_device_by_name_case_insensitive(_mock):
    """Device search should be case-insensitive."""
    device = find_device_by_name("blackstar")
    assert device is not None
    assert device.name == "Blackstar ID:Core V4"


@patch("guitar_amp_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES)
def test_find_device_by_name_returns_none_for_unknown(_mock):
    """Unknown device names should return None."""
    device = find_device_by_name("Nonexistent Device")
    assert device is None


@patch("guitar_amp_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES[1])
def test_live_device_name_returns_name_at_index(_mock):
    """The live name at an index backs the stream identity check."""
    assert live_device_name(1) == "Blackstar ID:Core V4"


@patch("guitar_amp_bot.device_finder.sd.query_devices", side_effect=RuntimeError("boom"))
def test_live_device_name_returns_none_on_portaudio_error(_mock):
    """A query failure must not raise: the caller treats None as a mismatch."""
    assert live_device_name(1) is None


@patch("guitar_amp_bot.device_finder.sd._initialize")
@patch("guitar_amp_bot.device_finder.sd._terminate")
def test_refresh_devices_reinitializes_portaudio(mock_terminate, mock_initialize):
    """Re-enumeration is the only way PortAudio notices a hot-unplug."""
    refresh_devices()
    mock_terminate.assert_called_once()
    mock_initialize.assert_called_once()


@patch("guitar_amp_bot.device_finder.sd._terminate", side_effect=RuntimeError("boom"))
def test_refresh_devices_survives_portaudio_error(_mock, caplog):
    """A failed refresh is logged and non-fatal; the identity check still guards."""
    with caplog.at_level(logging.WARNING, logger="guitar_amp_bot.device_finder"):
        refresh_devices()
    assert any("portaudio_refresh_failed" in r.message for r in caplog.records)


def test_device_queries_wait_for_a_portaudio_reinitialization():
    """Querying while another thread reinitializes PortAudio is undefined behaviour."""
    import threading

    reinit_started = threading.Event()
    release_reinit = threading.Event()
    query_done = threading.Event()

    def _slow_terminate():
        reinit_started.set()
        assert release_reinit.wait(timeout=5)

    with (
        patch("guitar_amp_bot.device_finder.sd._terminate", side_effect=_slow_terminate),
        patch("guitar_amp_bot.device_finder.sd._initialize"),
        patch("guitar_amp_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES),
    ):
        refresher = threading.Thread(target=refresh_devices)
        refresher.start()
        assert reinit_started.wait(timeout=5)

        querier = threading.Thread(target=lambda: (list_input_devices(), query_done.set()))
        querier.start()

        # The query must still be blocked behind the in-progress reinit.
        assert not query_done.wait(timeout=0.2)

        release_reinit.set()
        refresher.join(timeout=5)
        querier.join(timeout=5)

    assert query_done.is_set()


@patch("guitar_amp_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES)
def test_portaudio_lock_is_reentrant(_mock):
    """A caller holding the lock (stream open + verify) can still query devices."""
    from guitar_amp_bot.device_finder import portaudio_lock

    with portaudio_lock():
        assert find_device_by_name("blackstar") is not None


@patch(
    "guitar_amp_bot.device_finder.sd.query_hostapis",
    return_value=[{"name": "MME"}, {"name": "Windows WASAPI"}],
)
@patch(
    "guitar_amp_bot.device_finder.sd.query_devices",
    return_value=[
        {**FAKE_DEVICES[1], "hostapi": 0},
        {**FAKE_DEVICES[1], "hostapi": 1},
        {**FAKE_DEVICES[1], "hostapi": 7},
    ],
)
def test_list_input_devices_names_the_host_api(_devices, _hostapis):
    assert [d.hostapi for d in list_input_devices()] == ["MME", "Windows WASAPI", ""]


@patch("guitar_amp_bot.device_finder.sd.query_hostapis", side_effect=RuntimeError("boom"))
@patch("guitar_amp_bot.device_finder.sd.query_devices", return_value=FAKE_DEVICES)
def test_list_input_devices_survives_a_host_api_query_error(_devices, _hostapis):
    assert [d.hostapi for d in list_input_devices()] == ["", ""]


def test_exact_name_wins_over_a_longer_name_containing_it():
    """A full device name must select that device even if another name contains it."""
    devices = [_device(1, "USB Audio Device (2)"), _device(2, "USB Audio Device")]

    assert [d.index for d in match_devices(devices, "usb audio device")] == [2]


def test_ambiguous_substring_is_refused_with_the_candidates():
    devices = [
        _device(1, "Blackstar ID:Core V4"),
        _device(2, "USB Audio CODEC"),
        _device(3, "Focusrite USB"),
    ]

    with pytest.raises(AmbiguousDeviceError) as excinfo:
        match_devices(devices, "usb")

    assert excinfo.value.candidates == ["Focusrite USB", "USB Audio CODEC"]
    assert "usb" in str(excinfo.value)


def test_the_same_device_under_several_host_apis_is_not_ambiguous():
    """Windows lists each input under MME (truncated) as well as WASAPI."""
    devices = [
        _device(1, "Microphone (Blackstar ID:Core V", "MME"),
        _device(2, "Microphone (Blackstar ID:Core V4)", "Windows WASAPI"),
        _device(3, "Microphone (Blackstar ID:Core V4)", "Windows DirectSound"),
    ]

    assert [d.index for d in match_devices(devices, "blackstar")] == [2, 3, 1]


def test_select_device_prefers_the_native_host_api_over_mme():
    devices = [
        _device(1, "Blackstar ID:Core V4", "MME", rate=44100.0),
        _device(2, "Blackstar ID:Core V4", "Windows WASAPI"),
    ]

    assert select_device(devices, "Blackstar").index == 2


def test_select_device_skips_a_host_api_that_cannot_capture_48k(monkeypatch):
    def _check(*, device, **_kwargs):
        if device == 2:
            raise RuntimeError("Invalid sample rate")

    monkeypatch.setattr(device_finder.sd, "check_input_settings", _check)
    devices = [
        _device(1, "Blackstar ID:Core V4", "MME"),
        _device(2, "Blackstar ID:Core V4", "Windows WASAPI"),
    ]

    assert select_device(devices, "Blackstar").index == 1


def test_select_device_returns_the_best_match_even_when_none_can_capture(monkeypatch):
    """Opening it then fails with the reason, instead of claiming nothing matched."""
    devices = [_device(1, "Blackstar ID:Core V4", "MME", channels=1)]

    assert select_device(devices, "Blackstar").index == 1


def test_select_device_returns_none_without_a_match():
    assert select_device([_device(1, "Built-in Microphone")], "Blackstar") is None


def test_capture_problem_accepts_a_device_that_supports_48k_stereo():
    """A 44.1 kHz default is fine as long as PortAudio can open it at 48 kHz."""
    assert capture_problem(_device(1, "Interface", rate=44100.0)) is None


def test_capture_problem_checks_discord_format(monkeypatch):
    calls = []
    monkeypatch.setattr(
        device_finder.sd, "check_input_settings", lambda **kwargs: calls.append(kwargs)
    )

    capture_problem(_device(4, "Interface"))

    assert calls == [{"device": 4, "channels": 2, "dtype": "int16", "samplerate": 48000}]


def test_capture_problem_reports_a_mono_device():
    problem = capture_problem(_device(1, "Mono Mic", channels=1))

    assert problem is not None
    assert "1 input channel" in problem


def test_capture_problem_reports_an_unsupported_sample_rate(monkeypatch):
    def _reject(**_kwargs):
        raise RuntimeError("Invalid sample rate")

    monkeypatch.setattr(device_finder.sd, "check_input_settings", _reject)

    problem = capture_problem(_device(1, "Old Interface"))

    assert problem is not None
    assert "48000 Hz" in problem
    assert "Invalid sample rate" in problem


@patch("guitar_amp_bot.device_finder.refresh_devices")
def test_refresh_if_idle_reinitializes_with_no_stream_open(mock_refresh):
    assert refresh_devices_if_idle() is True
    mock_refresh.assert_called_once()


@patch("guitar_amp_bot.device_finder.refresh_devices")
def test_refresh_if_idle_leaves_an_open_stream_alone(mock_refresh):
    """Reinitializing PortAudio under a live stream is undefined behaviour."""
    note_stream_opened()
    try:
        assert refresh_devices_if_idle() is False
        mock_refresh.assert_not_called()
    finally:
        note_stream_closed()

    assert refresh_devices_if_idle() is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1", (1,)), ("1,2", (1, 2)), (" 3 , 4 ", (3, 4)), ("2,1", (2, 1))],
)
def test_parse_input_channels_accepts_one_or_two_inputs(raw, expected):
    assert parse_input_channels(raw) == expected
    assert format_input_channels(expected) == raw.replace(" ", "")


@pytest.mark.parametrize("raw", ["", "a", "1.5", "0", "-1", "1,1", "1,2,3", "1,"])
def test_parse_input_channels_rejects_anything_else(raw):
    with pytest.raises(ValueError, match="input"):
        parse_input_channels(raw)


def test_capture_problem_suggests_mono_for_a_single_input_device():
    problem = capture_problem(_device(1, "Guitar Link", channels=1))

    assert problem is not None
    assert "2 are required" in problem
    assert "INPUT_CHANNELS=1" in problem


def test_capture_problem_accepts_a_mono_device_for_mono_capture(monkeypatch):
    calls = []
    monkeypatch.setattr(device_finder.sd, "check_input_settings", lambda **kw: calls.append(kw))

    assert capture_problem(_device(1, "Guitar Link", channels=1), (1,)) is None
    assert calls[0]["channels"] == 1


def test_capture_problem_checks_every_input_up_to_the_highest_wanted(monkeypatch):
    calls = []
    monkeypatch.setattr(device_finder.sd, "check_input_settings", lambda **kw: calls.append(kw))

    assert capture_problem(_device(1, "Scarlett 4i4", channels=4), (3, 4)) is None
    assert calls[0]["channels"] == 4


def test_capture_problem_rejects_inputs_the_device_does_not_have():
    problem = capture_problem(_device(1, "Scarlett 2i2"), (3, 4))

    assert problem is not None
    assert "4 are required for INPUT_CHANNELS=3,4" in problem
    assert "mono" not in problem


def test_select_device_picks_a_mono_device_for_mono_capture():
    devices = [_device(1, "Guitar Link", channels=1)]

    assert select_device(devices, "guitar", (1,)).index == 1
