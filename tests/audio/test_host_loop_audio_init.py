"""Smoke test that host_loop initializes audio and ticks the listeners.

We don't run the full host loop — we exercise the audio init/tick helpers
that host_loop.py exposes for testability.
"""
import os
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")


def test_host_loop_exposes_audio_helpers():
    from engine import host_loop
    assert hasattr(host_loop, "init_audio")
    assert hasattr(host_loop, "tick_audio")
    assert hasattr(host_loop, "shutdown_audio")


def test_init_audio_uses_null_backend_when_env_set(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_AUDIO", "0")
    _dauntless_host = pytest.importorskip("_dauntless_host")
    from engine import host_loop
    host_loop.init_audio()
    log_ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "init" in log_ops
    host_loop.shutdown_audio()


def test_tick_audio_pushes_listener_pose(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_AUDIO", "0")
    _dauntless_host = pytest.importorskip("_dauntless_host")
    from engine import host_loop
    host_loop.init_audio()
    _dauntless_host.audio.clear_command_log()
    host_loop.tick_audio(
        camera_position=(0.0, 0.0, 0.0),
        camera_forward=(0.0, 0.0, -1.0),
        camera_up=(0.0, 1.0, 0.0),
        dt=0.016,
        player=None,
    )
    assert any(e["op"] == "set_listener"
               for e in _dauntless_host.audio.debug_command_log())
    host_loop.shutdown_audio()


def test_tick_audio_drives_the_hum_diagnostic(monkeypatch):
    """Wiring check for the Part 2 diagnostic (engine.audio.hum_diagnostic):
    every tick_audio call must feed it the same listener pose + player + dt
    the rest of the audio pipeline uses. maybe_report is itself the thing
    that stays silent/cheap unless a developer turned it on with F8 -- this
    only proves the call site plumbs the right arguments through."""
    monkeypatch.setenv("OPEN_STBC_AUDIO", "0")
    pytest.importorskip("_dauntless_host")
    from engine import host_loop
    from engine.audio import hum_diagnostic

    calls = []
    monkeypatch.setattr(hum_diagnostic, "maybe_report",
                         lambda **kw: calls.append(kw))

    host_loop.init_audio()
    host_loop.tick_audio(
        camera_position=(1.0, 2.0, 3.0),
        camera_forward=(0.0, 0.0, -1.0),
        camera_up=(0.0, 1.0, 0.0),
        dt=0.016,
        player="the-player-object",
    )
    host_loop.shutdown_audio()

    assert len(calls) == 1
    assert calls[0]["listener_pos"] == (1.0, 2.0, 3.0)
    assert calls[0]["player"] == "the-player-object"
    assert calls[0]["dt"] == 0.016


def test_register_default_sounds_is_gone():
    # The hardcoded stand-in is replaced by the real LoadBridge.LoadSounds()
    # + LoadTacticalSounds.LoadSounds() paths.
    import engine.audio.tg_sound as tg
    assert not hasattr(tg, "register_default_sounds")


def test_init_audio_backend_is_idempotent(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_AUDIO", "0")
    _dauntless_host = pytest.importorskip("_dauntless_host")
    from engine import host_loop
    host_loop.shutdown_audio()  # known-False flag regardless of suite order
    _dauntless_host.audio.clear_command_log()
    host_loop.init_audio_backend()  # first call must actually init
    assert "init" in [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    _dauntless_host.audio.clear_command_log()
    host_loop.init_audio_backend()  # second call must be a no-op
    assert "init" not in [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    host_loop.shutdown_audio()
