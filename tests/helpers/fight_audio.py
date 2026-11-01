"""Isolate a differential arm's hit audio from wall-clock speed and from the
fights before it.

A hit sound is one SDK RNG draw (LoadTacticalSounds.GetRandomSound), and the
death cascade rolls on the same RNG, so whether a hit plays a sound must not
differ between two arms of a native-vs-Python differential. Three things
decided it beyond the fight itself:

* the SDK's recent-sound memory (``LoadTacticalSounds.g_dRecentSounds``):
  each pick is narrowed by it, and no mission load resets it;
* hit_feedback's audio edge stamps (keyed by ``id(ship)``: a ship of this arm
  can reuse a freed id of the last);
* the WALL clock those gaps run on (hit_feedback's 0.15 s contact gap, and
  crew_speech / speak_queue's speech expiry): a slower arm plays more sounds.

``isolate_fight_audio(mp)`` clears both memories and runs every gap on the
game clock, through the given monkeypatch context (so the real clocks come
back when it closes). Used by the K1 and K2 differentials' scenes.
"""
import types

import App


def isolate_fight_audio(mp) -> None:
    import LoadTacticalSounds
    from engine.appc import crew_speech, hit_feedback, speak_queue

    LoadTacticalSounds.g_dRecentSounds.clear()
    hit_feedback.reset_audio_throttle()
    clock = types.SimpleNamespace(
        monotonic=lambda: App.g_kTimerManager.get_time())
    for module in (hit_feedback, crew_speech, speak_queue):
        mp.setattr(module, "time", clock)
